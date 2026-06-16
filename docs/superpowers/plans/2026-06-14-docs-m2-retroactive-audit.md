# M11 Retroactive Audit Lock-In Implementation Plan (docs-m2)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Lock in the M11 retroactive-audit work performed in docs-m1 by producing a portable, single-command verification harness (`scripts/m11-vocabulary-gates.sh`) plus an operator-facing audit-trail document (`docs/changelog/AUDIT.md`), then prove every REQ-08..12 and every doc-gate / closed-vocabulary / contributor-guide gate passes deterministically on Windows git-bash, WSL Ubuntu, and Linux CI.

**Architecture:** docs-m1 already inserted the 30 tag annotations across nine changelog files (one tag per dated heading, prose untouched). docs-m2 adds zero further edits to those nine files. Instead it adds two NEW artifacts: (a) a POSIX shell script under `scripts/` that encodes the four M11 vocabulary gates as runnable, idempotent checks for CI and contributors, and (b) a Markdown audit-trail document under `docs/changelog/` that records the per-entry tag rationale in the operator-facing location so future contributors do not need to read `docs/superpowers/plans/` to understand or contest a tag. No Python diff. No changelog-prose diff. No `CONTRIBUTING.md` diff.

**Tech Stack:** POSIX `sh` (no bashisms beyond `[ ]` test syntax already used elsewhere in the project), `grep -E`, `wc`, `sort`, `awk`, `find`, `xargs` — every binary already ships with Windows git-bash, WSL Ubuntu coreutils, and Linux CI coreutils. Markdown only for the audit-trail doc. git for commits.

---

## Inherited audit table (read-only — DO NOT re-derive)

docs-m1 already executed the per-entry tag assignment. The authoritative rationale table lives at `docs/superpowers/plans/2026-06-14-docs-m1-vocabulary-definition.md` lines 13–50. docs-m2 copies that table verbatim into `docs/changelog/AUDIT.md` in Task 9 — it does not re-derive or revise any tag choice. The current on-disk distribution (verified by Task 1) is 8 `FULL`, 20 `LITE`, 1 `SKELETON`, 0 `DEFERRED`, total 30 dated entries across nine files.

The nine files and their dated-heading line numbers (authoritative — every later REQ-11 ordering check compares against this list):

| File | Dated-heading line numbers |
|------|----------------------------|
| `docs/changelog/260401.md` | 3, 26, 61, 85 |
| `docs/changelog/260412.md` | 3, 34 |
| `docs/changelog/260413.md` | 3, 27, 51, 77, 104, 129, 148, 168, 195, 215, 250, 277, 302, 330 |
| `docs/changelog/260414.md` | 3 |
| `docs/changelog/260415.md` | 3, 33, 51 |
| `docs/changelog/260506.md` | 3 |
| `docs/changelog/260508.md` | 3, 25, 43 |
| `docs/changelog/260517.md` | 3 |
| `docs/changelog/260519.md` | 3 |

Total dated headings: 4 + 2 + 14 + 1 + 3 + 1 + 3 + 1 + 1 = **30**.

---

### Task 1: Capture the post-audit GREEN baseline and confirm M1's work is on-disk

**Files:**
- Read-only: `docs/changelog/*.md`, `CONTRIBUTING.md`

This task confirms docs-m1 already landed the 30 tag annotations and that the M1 commits are reachable on the current branch. It produces no commit; it only records the four numbers later tasks will assert against.

- [ ] **Step 1: Confirm dated-heading count is 30 across all changelog files**

```bash
grep -hE '^##+ [0-9]{6}' docs/changelog/*.md | wc -l
```

Expected: `30`

- [ ] **Step 2: Confirm every dated heading already carries one of the four allowed tags**

```bash
grep -hE '^##+ [0-9]{6}.*\[(FULL|LITE|SKELETON|DEFERRED)\]' docs/changelog/*.md | wc -l
```

Expected: `30`. If this prints anything other than `30`, stop — M1's audit work is incomplete and must be fixed inside M1, not patched here.

- [ ] **Step 3: Confirm the closed-vocabulary subset on dated headings is `{FULL, LITE, SKELETON}` (no fifth token)**

```bash
grep -hE '^##+ [0-9]{6}' docs/changelog/*.md | grep -oE '\[[A-Z]{3,9}\]' | sort -u
```

Expected exactly:

```text
[FULL]
[LITE]
[SKELETON]
```

`[DEFERRED]` is absent in the historical audit because no historical entry warranted it — this is allowed by the spec (the gate text is "returns only the four tokens … and no others"; a subset of the closed set passes).

- [ ] **Step 4: Confirm CONTRIBUTING.md already defines the four tags as inline code (REQ-13)**

```bash
for tag in FULL LITE SKELETON DEFERRED; do printf '%s ' "$tag"; grep -c -F "\`$tag\`" CONTRIBUTING.md; done
```

Expected: each tag prints `1`.

- [ ] **Step 5: No commit (baseline-recording task only)**

Hold the four numbers (`30`, `30`, three-line tag set, four ones) in the executor's working notes; Tasks 4, 6, 7, and 12 re-assert them.

---

### Task 2: Write the failing test — the M11 vocabulary gate script does not exist yet

**Files:**
- Read-only: `scripts/`

This task confirms `scripts/m11-vocabulary-gates.sh` is absent so Task 3's creation is genuine TDD-RED-then-GREEN. It produces no commit.

- [ ] **Step 1: Confirm the file does not exist**

```bash
test -e scripts/m11-vocabulary-gates.sh && echo "FAIL: script already exists" || echo "OK: RED — script missing"
```

Expected: `OK: RED — script missing`. If it prints `FAIL`, stop and reconcile with a previously aborted execution of this plan before continuing.

- [ ] **Step 2: Confirm the script's intended invocation fails**

```bash
sh scripts/m11-vocabulary-gates.sh 2>&1 | head -1
```

Expected: an error such as `sh: scripts/m11-vocabulary-gates.sh: No such file or directory` (exact wording varies by platform — Windows git-bash, WSL, and Linux all produce a similar "no such file" message). The point is the command does not exit 0.

- [ ] **Step 3: No commit**

---

### Task 3: Create the M11 vocabulary gate script — minimum content to GREEN the REQ-12 + closed-vocabulary checks

**Files:**
- Create: `scripts/m11-vocabulary-gates.sh`

The script encodes the doc-only M11 quality gates as a single command. It must use only POSIX `sh` features so it runs identically on Windows git-bash, WSL Ubuntu, and Linux CI without modification (NFR). It must exit non-zero on any gate failure and print one human-readable line per gate.

- [ ] **Step 1: Create the script with executable shebang and the first two gates (REQ-12 vocabulary-coverage and closed-vocabulary)**

Write file `scripts/m11-vocabulary-gates.sh` with exactly this content:

```sh
#!/bin/sh
# M11 changelog vocabulary gates — portable across Windows git-bash, WSL Ubuntu, and Linux CI.
# Exits 0 only if every M11 doc-gate passes.

set -eu

REPO_ROOT="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
cd "$REPO_ROOT"

fail() { printf 'FAIL: %s\n' "$1" >&2; exit 1; }
pass() { printf 'PASS: %s\n' "$1"; }

# Gate 1 — REQ-12 vocabulary-coverage: dated-heading count == tagged-heading count.
DATED=$(grep -hE '^##+ [0-9]{6}' docs/changelog/*.md | wc -l | tr -d ' ')
TAGGED=$(grep -hE '^##+ [0-9]{6}.*\[(FULL|LITE|SKELETON|DEFERRED)\]' docs/changelog/*.md | wc -l | tr -d ' ')
[ "$DATED" = "$TAGGED" ] || fail "REQ-12 vocabulary-coverage: dated=$DATED tagged=$TAGGED"
pass "REQ-12 vocabulary-coverage (dated=$DATED tagged=$TAGGED)"

# Gate 2 — Closed-vocabulary: any bracketed uppercase 3..9-letter token on a dated heading
# must be a member of {FULL, LITE, SKELETON, DEFERRED}.
EXTRA=$(grep -hE '^##+ [0-9]{6}' docs/changelog/*.md \
  | grep -oE '\[[A-Z]{3,9}\]' \
  | sort -u \
  | grep -vE '^\[(FULL|LITE|SKELETON|DEFERRED)\]$' || true)
[ -z "$EXTRA" ] || fail "Closed-vocabulary: foreign tokens on dated headings: $EXTRA"
pass "Closed-vocabulary (only allowed tokens present)"
```

- [ ] **Step 2: Mark it executable so direct invocation works on Linux / WSL**

```bash
chmod +x scripts/m11-vocabulary-gates.sh
```

Note: Windows filesystems do not preserve the executable bit, so the script is also invokable via `sh scripts/m11-vocabulary-gates.sh` — Step 4 uses that form for portability.

- [ ] **Step 3: Run the script and confirm it now prints two PASS lines and exits 0**

```bash
sh scripts/m11-vocabulary-gates.sh
echo "exit=$?"
```

Expected output (exactly):

```text
PASS: REQ-12 vocabulary-coverage (dated=30 tagged=30)
PASS: Closed-vocabulary (only allowed tokens present)
exit=0
```

- [ ] **Step 4: Confirm the script works the same way from a different CWD (portability)**

```bash
( cd docs && sh ../scripts/m11-vocabulary-gates.sh )
```

Expected: the same two PASS lines and exit 0. The `REPO_ROOT` resolution inside the script must make CWD irrelevant.

- [ ] **Step 5: Commit**

```bash
git add scripts/m11-vocabulary-gates.sh
git commit --trailer "Generated-By: claude-opus-4-7" -m "feat(m11): seed portable changelog-vocabulary gate script"
```

---

### Task 4: Extend the gate script with the REQ-09 sub-heading isolation gate

**Files:**
- Modify: `scripts/m11-vocabulary-gates.sh`

REQ-09 states: "tags apply only to the dated entry headings … Sub-section headings inside an entry such as `### Summary`, `### Added`, `### Changed`, `### Fixed`, `### Removed`, `### Files`, and `### QA Notes` must not carry tags." The gate is the inverse: any heading line that contains a tag in brackets must also begin with a six-digit date. Hardcoding the sub-section names is brittle — a future contributor could invent a new sub-heading. The check below works for any sub-heading wording.

- [ ] **Step 1: Confirm the gate currently does not exist (RED)**

```bash
grep -F 'Gate 3' scripts/m11-vocabulary-gates.sh && echo "FAIL: gate already exists" || echo "OK: RED — gate 3 missing"
```

Expected: `OK: RED — gate 3 missing`.

- [ ] **Step 2: Append Gate 3 to the script**

Open `scripts/m11-vocabulary-gates.sh` and add the following block at the end of the file (after Gate 2's `pass` line, before EOF):

```sh

# Gate 3 — REQ-09 sub-heading isolation: any tagged heading must also be a dated heading.
NONDATED_TAGGED=$(grep -hE '^##+' docs/changelog/*.md \
  | grep -E '\[(FULL|LITE|SKELETON|DEFERRED)\]' \
  | grep -vE '^##+ [0-9]{6}' || true)
[ -z "$NONDATED_TAGGED" ] || fail "REQ-09 sub-heading isolation: non-dated heading carries a tag: $NONDATED_TAGGED"
pass "REQ-09 sub-heading isolation (only dated headings tagged)"
```

- [ ] **Step 3: Run the script and confirm three PASS lines**

```bash
sh scripts/m11-vocabulary-gates.sh
echo "exit=$?"
```

Expected:

```text
PASS: REQ-12 vocabulary-coverage (dated=30 tagged=30)
PASS: Closed-vocabulary (only allowed tokens present)
PASS: REQ-09 sub-heading isolation (only dated headings tagged)
exit=0
```

- [ ] **Step 4: Negative-test Gate 3 in a throwaway scratch file (DO NOT commit this scratch file)**

To prove Gate 3 actually fails when a sub-heading is mistakenly tagged, create a temporary fixture inside `docs/changelog/`, run the script, then remove the fixture. The script reads `docs/changelog/*.md`, so the temp file is auto-included.

```bash
printf '%s\n' '### [FULL] Bad sub-heading' > docs/changelog/_temp_gate3_negative.md
sh scripts/m11-vocabulary-gates.sh; echo "exit=$?"
rm docs/changelog/_temp_gate3_negative.md
```

Expected: the third gate prints `FAIL: REQ-09 sub-heading isolation: non-dated heading carries a tag: ### [FULL] Bad sub-heading` and the script exits non-zero. After `rm`, running the script again must return to three PASS lines and exit 0.

- [ ] **Step 5: Confirm clean state after the negative test**

```bash
test ! -e docs/changelog/_temp_gate3_negative.md && echo "OK: scratch file removed"
sh scripts/m11-vocabulary-gates.sh
echo "exit=$?"
```

Expected: `OK: scratch file removed`, three PASS lines, `exit=0`.

- [ ] **Step 6: Commit**

```bash
git add scripts/m11-vocabulary-gates.sh
git commit --trailer "Generated-By: claude-opus-4-7" -m "feat(m11): add sub-heading isolation gate (REQ-09) to vocabulary gates"
```

---

### Task 5: Extend the gate script with the REQ-13 contributor-guide gate

**Files:**
- Modify: `scripts/m11-vocabulary-gates.sh`

REQ-13: "the four allowed tag strings must appear in `CONTRIBUTING.md` exactly once each as fenced inline code in the definition list so they are machine-greppable as a closed vocabulary reference." Gate enforces count ≥ 1 per tag (the spec gate says "at least one occurrence"; the M1 plan asserts each appears exactly once — we keep the gate at the spec's "≥ 1" floor to remain robust to future minor wording tweaks inside docs-m1's scope).

- [ ] **Step 1: Confirm Gate 4 missing**

```bash
grep -F 'Gate 4' scripts/m11-vocabulary-gates.sh && echo "FAIL: gate already exists" || echo "OK: RED — gate 4 missing"
```

Expected: `OK: RED — gate 4 missing`.

- [ ] **Step 2: Append Gate 4**

Add this block at the end of `scripts/m11-vocabulary-gates.sh`:

```sh

# Gate 4 — REQ-13 contributor-guide vocabulary: each tag string must appear at
# least once as fenced inline code in CONTRIBUTING.md.
MISSING=""
for TAG in FULL LITE SKELETON DEFERRED; do
  if ! grep -qF "\`$TAG\`" CONTRIBUTING.md; then
    MISSING="$MISSING $TAG"
  fi
done
[ -z "$MISSING" ] || fail "REQ-13 contributor-guide: missing inline-code tags:$MISSING"
pass "REQ-13 contributor-guide (all four tags present as inline code)"
```

- [ ] **Step 3: Run the script**

```bash
sh scripts/m11-vocabulary-gates.sh
echo "exit=$?"
```

Expected four PASS lines:

```text
PASS: REQ-12 vocabulary-coverage (dated=30 tagged=30)
PASS: Closed-vocabulary (only allowed tokens present)
PASS: REQ-09 sub-heading isolation (only dated headings tagged)
PASS: REQ-13 contributor-guide (all four tags present as inline code)
exit=0
```

- [ ] **Step 4: Commit**

```bash
git add scripts/m11-vocabulary-gates.sh
git commit --trailer "Generated-By: claude-opus-4-7" -m "feat(m11): add contributor-guide gate (REQ-13) to vocabulary gates"
```

---

### Task 6: Extend the gate script with the REQ-11 ordering-preservation gate

**Files:**
- Modify: `scripts/m11-vocabulary-gates.sh`

REQ-11: "preserve the original chronological order of entries within each file and across files; no entry may be moved, merged, split, deleted, or re-dated." This gate freezes the dated-heading line-number signature per file against the authoritative table at the top of this plan. If a future contributor reorders an entry, this gate fails before review.

- [ ] **Step 1: Confirm Gate 5 missing**

```bash
grep -F 'Gate 5' scripts/m11-vocabulary-gates.sh && echo "FAIL: gate already exists" || echo "OK: RED — gate 5 missing"
```

Expected: `OK: RED — gate 5 missing`.

- [ ] **Step 2: Append Gate 5**

Add this block at the end of `scripts/m11-vocabulary-gates.sh`:

```sh

# Gate 5 — REQ-11 ordering preservation: dated-heading line numbers per file
# must match the M1 audit's frozen signature. Format: "file:lineA,lineB,...".
# Files under docs/changelog/ that contain zero dated headings (such as the
# operator-facing audit-trail document added by docs-m2) are excluded from the
# signature so the gate stays stable as adjacent docs are added.
EXPECTED="\
docs/changelog/260401.md:3,26,61,85
docs/changelog/260412.md:3,34
docs/changelog/260413.md:3,27,51,77,104,129,148,168,195,215,250,277,302,330
docs/changelog/260414.md:3
docs/changelog/260415.md:3,33,51
docs/changelog/260506.md:3
docs/changelog/260508.md:3,25,43
docs/changelog/260517.md:3
docs/changelog/260519.md:3"

ACTUAL=$(for F in docs/changelog/*.md; do
  LINES=$(grep -nE '^##+ [0-9]{6}' "$F" | cut -d: -f1 | tr '\n' ',' | sed 's/,$//')
  [ -n "$LINES" ] || continue
  printf '%s:%s\n' "$F" "$LINES"
done)

# Compare via temp files — POSIX sh has no process substitution, so <(...) is
# avoided to keep the script runnable under dash on stock Debian/Ubuntu CI.
TMP_EXPECTED=$(mktemp 2>/dev/null || printf '/tmp/m11_exp.%s' "$$")
TMP_ACTUAL=$(mktemp 2>/dev/null || printf '/tmp/m11_act.%s' "$$")
printf '%s\n' "$EXPECTED" > "$TMP_EXPECTED"
printf '%s\n' "$ACTUAL" > "$TMP_ACTUAL"
DIFF=$(diff "$TMP_EXPECTED" "$TMP_ACTUAL" || true)
rm -f "$TMP_EXPECTED" "$TMP_ACTUAL"
[ -z "$DIFF" ] || fail "REQ-11 ordering-preservation drift detected:
$DIFF"
pass "REQ-11 ordering-preservation (all nine files match frozen line signature)"
```

- [ ] **Step 3: Run the script**

```bash
sh scripts/m11-vocabulary-gates.sh
echo "exit=$?"
```

Expected: five PASS lines and `exit=0`.

- [ ] **Step 4: Negative-test by temporarily injecting a blank line**

Insert a blank line at the top of `docs/changelog/260519.md` so its dated heading drifts from line 3 to line 4, then prove Gate 5 fails. Then restore.

```bash
cp docs/changelog/260519.md /tmp/260519.bak
printf '\n%s' "$(cat docs/changelog/260519.md)" > docs/changelog/260519.md
sh scripts/m11-vocabulary-gates.sh; echo "exit=$?"
cp /tmp/260519.bak docs/changelog/260519.md
rm /tmp/260519.bak
sh scripts/m11-vocabulary-gates.sh; echo "exit=$?"
```

Expected: the first run prints `FAIL: REQ-11 ordering-preservation drift detected:` with a diff naming `260519.md`, exit non-zero. The second run (after restore) prints five PASS lines and `exit=0`.

- [ ] **Step 5: Verify the restore left no diff against HEAD**

```bash
git diff -- docs/changelog/260519.md
```

Expected: no output (working tree matches HEAD).

- [ ] **Step 6: Commit**

```bash
git add scripts/m11-vocabulary-gates.sh
git commit --trailer "Generated-By: claude-opus-4-7" -m "feat(m11): add ordering-preservation gate (REQ-11) to vocabulary gates"
```

---

### Task 7: Extend the gate script with a clean-diff hygiene gate (REQ-10 + NFR whitespace)

**Files:**
- Modify: `scripts/m11-vocabulary-gates.sh`

REQ-10 forbids modifying prose body, bullet content, file list, or QA notes of any historical entry — only the heading line may change. The NFR forbids whitespace-only churn, trailing-whitespace introduction, and line-ending changes. This gate verifies that, against `main`, every changed line under `docs/changelog/` is a dated-heading line. The gate also runs `git diff --check` to catch trailing whitespace and CRLF errors.

- [ ] **Step 1: Confirm Gate 6 missing**

```bash
grep -F 'Gate 6' scripts/m11-vocabulary-gates.sh && echo "FAIL: gate already exists" || echo "OK: RED — gate 6 missing"
```

Expected: `OK: RED — gate 6 missing`.

- [ ] **Step 2: Append Gate 6**

Add this block at the end of `scripts/m11-vocabulary-gates.sh`:

```sh

# Gate 6 — REQ-10 prose-immutability + whitespace hygiene against the integration base.
# BASE env var lets CI override (default = origin/main, falling back to main if unfetched).
# AUDIT.md is excluded because it is a wholly new operator-facing document — every
# line is an addition, none describe a historical entry's prose, and REQ-10 only
# constrains "the prose body, bullet content, file list, or QA notes of any
# historical entry" (spec lines 22–23). The exclude pathspec keeps that intent.
BASE="${BASE:-origin/main}"
if ! git rev-parse --verify --quiet "$BASE" >/dev/null; then BASE=main; fi
if git rev-parse --verify --quiet "$BASE" >/dev/null; then
  NON_HEADING=$(git diff -U0 "$BASE"...HEAD -- 'docs/changelog/*.md' ':!docs/changelog/AUDIT.md' \
    | grep -E '^[+-][^+-]' \
    | grep -vE '^[+-]## [0-9]{6}' || true)
  [ -z "$NON_HEADING" ] || fail "REQ-10 prose-immutability: non-heading changes under docs/changelog/:
$NON_HEADING"
  pass "REQ-10 prose-immutability (only dated headings changed vs $BASE)"

  # Whitespace hygiene on every changed file we are responsible for.
  git diff --check "$BASE"...HEAD -- 'docs/changelog/*.md' CONTRIBUTING.md scripts/m11-vocabulary-gates.sh >/dev/null \
    || fail "Whitespace hygiene: git diff --check reported violations"
  pass "Whitespace hygiene (no trailing ws, no CRLF mix on changed files)"
else
  printf 'SKIP: no %s ref available — gate 6 skipped (acceptable for shallow CI checkouts)\n' "$BASE"
fi
```

- [ ] **Step 3: Run the script and confirm seven PASS lines (or two SKIP lines if the base ref is unavailable)**

```bash
sh scripts/m11-vocabulary-gates.sh
echo "exit=$?"
```

Expected in a normal workspace where `origin/main` or `main` is fetched: seven PASS lines and `exit=0`. In a worktree where only the current branch is present, the gate prints one `SKIP:` line — this is acceptable per the spec gate's portability NFR (CI environments may run a shallow checkout) and Task 11 below provides a non-skippable fallback.

- [ ] **Step 4: Commit**

```bash
git add scripts/m11-vocabulary-gates.sh
git commit --trailer "Generated-By: claude-opus-4-7" -m "feat(m11): add prose-immutability + whitespace gate (REQ-10) to vocabulary gates"
```

---

### Task 8: Add line-ending portability check to the gate script

**Files:**
- Modify: `scripts/m11-vocabulary-gates.sh`

The NFR forbids line-ending changes. On Windows, `git config core.autocrlf` can silently rewrite endings during checkout. This gate spot-checks that `CONTRIBUTING.md` and every `docs/changelog/*.md` is LF-only on disk, which Gate 6's `git diff --check` would also catch — but this gate runs unconditionally (no `$BASE` requirement), which makes it a non-skippable last line of defense.

- [ ] **Step 1: Confirm Gate 7 missing**

```bash
grep -F 'Gate 7' scripts/m11-vocabulary-gates.sh && echo "FAIL: gate already exists" || echo "OK: RED — gate 7 missing"
```

Expected: `OK: RED — gate 7 missing`.

- [ ] **Step 2: Append Gate 7**

Add this block at the end of `scripts/m11-vocabulary-gates.sh`:

```sh

# Gate 7 — Line-ending portability: every file the M11 vocab gates inspect must be LF-only.
CRLF_HITS=""
for F in CONTRIBUTING.md docs/changelog/*.md; do
  # Detect a literal CR (\r) anywhere in the file. Portable across GNU and BSD grep.
  if LC_ALL=C grep -l "$(printf '\r')" "$F" >/dev/null 2>&1; then
    CRLF_HITS="$CRLF_HITS $F"
  fi
done
[ -z "$CRLF_HITS" ] || fail "Line-ending portability: CRLF detected in:$CRLF_HITS"
pass "Line-ending portability (CONTRIBUTING.md + docs/changelog/*.md are LF-only)"
```

- [ ] **Step 3: Run the script and confirm the new gate**

```bash
sh scripts/m11-vocabulary-gates.sh
echo "exit=$?"
```

Expected on a clean LF workspace: eight PASS lines (Gate 6 still passes if base ref present) or seven PASS lines + one SKIP. `exit=0` in both cases.

- [ ] **Step 4: Commit**

```bash
git add scripts/m11-vocabulary-gates.sh
git commit --trailer "Generated-By: claude-opus-4-7" -m "feat(m11): add line-ending portability gate to vocabulary gates"
```

---

### Task 9: Create the operator-facing audit-trail document

**Files:**
- Create: `docs/changelog/AUDIT.md`

The NFR "audit reasoning for each retroactive tag assignment must be recorded in the M11 implementation plan" is technically satisfied by docs-m1's plan, but that plan lives in `docs/superpowers/plans/` — a planning location future contributors are unlikely to discover when they are looking at the changelog itself. This task copies the rationale table into the changelog directory as a stable, operator-facing reference. The audit-trail document does NOT re-derive any tag; it transcribes the M1 plan's table verbatim plus a one-paragraph methodology note.

- [ ] **Step 1: Confirm the file does not exist (RED)**

```bash
test -e docs/changelog/AUDIT.md && echo "FAIL: already exists" || echo "OK: RED — audit-trail missing"
```

Expected: `OK: RED — audit-trail missing`.

- [ ] **Step 2: Write the audit-trail document**

Write file `docs/changelog/AUDIT.md` with exactly this content:

```markdown
# Changelog tag audit trail (M11)

This document records the rationale for the scope tag (`FULL`, `LITE`, `SKELETON`, or `DEFERRED`) assigned to every dated entry that existed when M11 — the closed four-tag vocabulary — was introduced. The vocabulary itself is defined in `CONTRIBUTING.md`. The M11 spec is `docs/superpowers/specs/2026-06-14-m11-changelog-vocabulary.md`. The M11 implementation plans are at `docs/superpowers/plans/2026-06-14-docs-m1-vocabulary-definition.md` (vocabulary + tag insertion) and `docs/superpowers/plans/2026-06-14-docs-m2-retroactive-audit.md` (audit lock-in and verification harness).

## Methodology

Every dated entry across `docs/changelog/260401.md` through `docs/changelog/260519.md` was inspected directly. The chosen tag reflects the scope evidenced by the entry's own `### Summary`, `### Added`, `### Changed`, `### Fixed`, `### Files`, and `### QA Notes` blocks — not by git history or by the reviewer's recall. The four tags are defined in `CONTRIBUTING.md`. The vocabulary is closed; no fifth tag is permitted inside M11. A future contributor who believes a tag is wrong should open a follow-up PR that updates only the heading line of the affected entry (REQ-09, REQ-10) and updates the corresponding row in this document.

## Per-entry rationale

| # | File | Line | Heading (after tagging) | Tag | Rationale |
|---|------|------|-------------------------|-----|-----------|
| 1 | `docs/changelog/260401.md` | 3 | `## 260412 - [LITE] Pure Skill Install Layout` | `LITE` | Installer + runtime + smoke-test changes shipped together; no QA-Notes block records test runs, so depth is reduced. |
| 2 | `docs/changelog/260401.md` | 26 | `## 260401-22:47:02 - [LITE] Prepare repository for open source release` | `LITE` | Repo-wiring entry (MIT, CI, smoke harness, contributor docs); QA Notes literally `N/A`. |
| 3 | `docs/changelog/260401.md` | 61 | `## 260414-10:30:57 - [FULL] Harden tmux runtime for non-default shells` | `FULL` | New module plus dedicated tests; QA Notes run `compileall` and `unittest test_tmux_runtime`. |
| 4 | `docs/changelog/260401.md` | 85 | `## 260414-12:07:46 - [FULL] Fix Claude runner sessions that stay open at the prompt after command completion` | `FULL` | Targeted fix plus regression test updates; QA Notes run `unittest test_tmux_runtime` and `compileall`. |
| 5 | `docs/changelog/260412.md` | 3 | `## 260412-02:41:53 - [LITE] Migrate story automator installer to pure skill layout` | `LITE` | Large installer/runtime migration with bundled smoke updates; QA Notes `N/A`. |
| 6 | `docs/changelog/260412.md` | 34 | `## 260412-04:50:44 - [LITE] Close review gaps in skill migration` | `LITE` | Follow-up review-gap fixes + smoke; QA Notes `N/A`. |
| 7 | `docs/changelog/260413.md` | 3 | `## 260413-09:14:32 - [FULL] Restore verify-step retry contract` | `FULL` | Fix + unit + smoke; QA Notes run `unittest test_success_verifiers` and `smoke-test.sh`. |
| 8 | `docs/changelog/260413.md` | 27 | `## 260413-08:05:51 - [LITE] Wire policy-backed success verifiers` | `LITE` | New registry shipped with unit coverage but QA Notes `N/A`. |
| 9 | `docs/changelog/260413.md` | 51 | `## 260413-09:26:29 - [LITE] Tighten state policy compatibility helpers` | `LITE` | Compatibility fixes with tests; QA Notes `N/A`. |
| 10 | `docs/changelog/260413.md` | 77 | `## 260413-08:39:42 - [FULL] Route create validation through shared verifier` | `FULL` | Helper added, smoke + tests updated; QA Notes run `npm run verify`. |
| 11 | `docs/changelog/260413.md` | 104 | `## 260413-08:34:25 - [FULL] Harden success verifier review fixes` | `FULL` | Fix + tests + smoke; QA Notes run `npm run verify`. |
| 12 | `docs/changelog/260413.md` | 129 | `## 260413-11:35:00 - [FULL] Verify packed npx install path` | `FULL` | Release-prep entry that re-pinned the publish smoke path; QA Notes run `npm run verify`. |
| 13 | `docs/changelog/260413.md` | 148 | `## 260413-03:41:50 - [LITE] Stabilize Codex tmux review sessions` | `LITE` | Fix + smoke contract updates; QA Notes `N/A`. |
| 14 | `docs/changelog/260413.md` | 168 | `## 260413-05:03:47 - [LITE] Add comprehensive automator documentation` | `LITE` | Docs-only rewrite; no test impact and no QA Notes block. |
| 15 | `docs/changelog/260413.md` | 195 | `## 260413-06:34:01 - [SKELETON] Add JSON settings implementation plan` | `SKELETON` | Planning packet — directory tree of plan docs with no behavioral wiring, no tests. |
| 16 | `docs/changelog/260413.md` | 215 | `## 260413-07:29:16 - [LITE] Add JSON runtime policy foundation` | `LITE` | Large impl + bundled data + tests, but QA Notes `N/A`. |
| 17 | `docs/changelog/260413.md` | 250 | `## 260413-07:55:28 - [LITE] Harden runtime policy snapshot handling` | `LITE` | Snapshot/marker fixes + regression coverage; QA Notes `N/A`. |
| 18 | `docs/changelog/260413.md` | 277 | `## 260413-09:13:20 - [LITE] Enforce snapshot-only resume semantics` | `LITE` | Fixes + tests + operator docs; QA Notes `N/A`. |
| 19 | `docs/changelog/260413.md` | 302 | `## 260413-11:00:47 - [LITE] Harden parser runtime and validator compatibility` | `LITE` | Parser/validator hardening + tests; QA Notes `N/A`. |
| 20 | `docs/changelog/260413.md` | 330 | `## 260413-21:53:12 - [LITE] Close state-summary and validator compatibility gaps` | `LITE` | Compatibility-gap fixes + regression coverage; QA Notes `N/A`. |
| 21 | `docs/changelog/260414.md` | 3 | `## 260414-21:51:35 - [LITE] Harden snapshot and verifier review fixes` | `LITE` | Review-loop hardening + tests + docs; QA Notes `N/A`. |
| 22 | `docs/changelog/260415.md` | 3 | `## 260415-01:20:16 - [LITE] Harden policy resume and review parsing` | `LITE` | Snapshot/parser fixes + regression coverage; QA Notes `N/A`. |
| 23 | `docs/changelog/260415.md` | 33 | `## 260415-06:47:15 - [LITE] Harden tmux prompt and monitor contract failures` | `LITE` | Fail-closed fixes + regression coverage; QA Notes `N/A`. |
| 24 | `docs/changelog/260415.md` | 51 | `## 260415-07:54:52 - [LITE] Tighten tmux monitor output verification` | `LITE` | Fixes + regressions for verifier outcome; QA Notes `N/A`. |
| 25 | `docs/changelog/260506.md` | 3 | `## 260506-19:21:58 - [LITE] Support SKILL-only BMAD dependency installs` | `LITE` | Install + runtime relaxation + tests + docs; QA Notes `N/A`. |
| 26 | `docs/changelog/260508.md` | 3 | `## 260508-07:58:11 - [LITE] Align Claude plugin marketplace metadata` | `LITE` | Metadata + docs polish; QA Notes `N/A`. |
| 27 | `docs/changelog/260508.md` | 25 | `## 260508-01:22:06 - [LITE] Publish refreshed npx installer` | `LITE` | Pure version-bump release entry; QA Notes `N/A`. |
| 28 | `docs/changelog/260508.md` | 43 | `## 260508-01:17:06 - [LITE] Repackage automator as self-contained skills` | `LITE` | Large repackage + docs + tests update; QA Notes `N/A`. |
| 29 | `docs/changelog/260517.md` | 3 | `## 260517 - [FULL] Release Codex Runtime Support` | `FULL` | Release milestone with multi-root installer + tests + version bumps; QA Notes run `npm run verify`. |
| 30 | `docs/changelog/260519.md` | 3 | `## 260519 - [FULL] Per-Task Model Selection` | `FULL` | Large impl + 26 new tests + 4 review passes; QA Notes run 229-test discover and smoke. |

## Distribution

8 `FULL`, 20 `LITE`, 1 `SKELETON`, 0 `DEFERRED`. `DEFERRED` is reserved for future entries; the closed-vocabulary gate explicitly permits a subset of the four tags to appear.
```

- [ ] **Step 3: Confirm the file is LF-only and has no trailing whitespace**

```bash
LC_ALL=C grep -l "$(printf '\r')" docs/changelog/AUDIT.md && echo "FAIL: CRLF" || echo "OK: LF-only"
grep -nE ' +$' docs/changelog/AUDIT.md && echo "FAIL: trailing ws" || echo "OK: no trailing ws"
```

Expected: `OK: LF-only` then `OK: no trailing ws`.

- [ ] **Step 4: Re-run the vocabulary gate script to confirm AUDIT.md does not perturb any gate**

`AUDIT.md` lives under `docs/changelog/` and is therefore globbed by `docs/changelog/*.md`. Confirm it does not break REQ-12 or the closed-vocabulary gate.

```bash
sh scripts/m11-vocabulary-gates.sh
echo "exit=$?"
```

Expected: same PASS lines as before, `exit=0`. AUDIT.md contains zero lines matching `^##+ [0-9]{6}` (its headings are `# …` and `## Methodology`, `## Per-entry rationale`, `## Distribution`), so it does not affect the dated-heading count of 30.

- [ ] **Step 5: Spot-check that the rationale table's row count equals the dated-heading total**

```bash
ROWS=$(grep -cE '^\| [0-9]+ \| `docs/changelog/' docs/changelog/AUDIT.md)
echo "rows=$ROWS"
```

Expected: `rows=30`.

- [ ] **Step 6: Commit**

```bash
git add docs/changelog/AUDIT.md
git commit --trailer "Generated-By: claude-opus-4-7" -m "docs(m11): add operator-facing changelog tag audit trail"
```

---

### Task 10: Add an npm script alias so the gate is discoverable via `npm run`

**Files:**
- Modify: `package.json` (add one entry to `scripts`)

The existing `npm run verify` chain (`test:python`, `pack:dry-run`, `test:cli`, `test:smoke`) runs the inherited Python gates. The new vocabulary gates should be discoverable the same way so contributors invoke them with `npm run gates:vocab` rather than memorizing the script path. This is a one-line change.

- [ ] **Step 1: Read the current `scripts` block**

```bash
sed -n '/"scripts": {/,/^  }/p' package.json
```

Record the current keys for use in Step 2 (so the new entry preserves comma-and-quote conventions).

- [ ] **Step 2: Insert one new entry, `"gates:vocab": "sh scripts/m11-vocabulary-gates.sh"`, into the `scripts` block**

The current `scripts` block (as verified in Step 1) ends with `"verify": "npm run test:python && npm run pack:dry-run && npm run test:cli && npm run test:smoke"` and is preceded by `"test:smoke": "bash scripts/smoke-test.sh",`. Insert the new key **between** `test:smoke` and `verify` so the alphabetic-ish grouping (test/pack/verify last) is preserved.

Use the `Edit` tool with this exact pair (preserves the file's four-space JSON indentation):

- old:
  ```
      "test:smoke": "bash scripts/smoke-test.sh",
      "verify": "npm run test:python && npm run pack:dry-run && npm run test:cli && npm run test:smoke"
  ```
- new:
  ```
      "test:smoke": "bash scripts/smoke-test.sh",
      "gates:vocab": "sh scripts/m11-vocabulary-gates.sh",
      "verify": "npm run test:python && npm run pack:dry-run && npm run test:cli && npm run test:smoke"
  ```

If Step 1 revealed a different trailing-key shape (for example, a future M-numbered milestone has already inserted another script), anchor on the *actual* last two entries seen in Step 1 instead and follow the same "insert before the last" pattern. **Preserve the file's existing four-space indentation.**

- [ ] **Step 3: Confirm `package.json` still parses as valid JSON**

```bash
node -e "JSON.parse(require('fs').readFileSync('package.json','utf8'))" && echo "OK: JSON valid"
```

Expected: `OK: JSON valid`. If this prints a parse error, the most likely cause is a stray comma — re-read the file and fix.

- [ ] **Step 4: Run the new alias**

```bash
npm run gates:vocab
```

Expected: the same PASS-lines output as `sh scripts/m11-vocabulary-gates.sh`, exit 0. npm prefixes with its own banner (`> bmad-story-automator@x.y.z gates:vocab`) — that is normal.

- [ ] **Step 5: Confirm the diff to `package.json` is exactly one added line**

```bash
git diff --numstat -- package.json
```

Expected: `1\t0\tpackage.json` (one line added, zero removed).

- [ ] **Step 6: Commit**

```bash
git add package.json
git commit --trailer "Generated-By: claude-opus-4-7" -m "chore(m11): expose vocabulary gate as npm run gates:vocab"
```

---

### Task 11: Verify the inherited Python quality gates remain GREEN (no Python diff in M2)

**Files:**
- Read-only: `skills/bmad-story-automator/`, `tests/`

M2 ships zero Python diff. All six inherited Python gates must keep their previous statuses. This task is a guard against accidental drift introduced anywhere in M2's commits.

- [ ] **Step 1: Confirm no Python or test file changed in any M2 commit**

```bash
git diff --name-only main...HEAD -- '*.py' 'tests/' | head && echo "(end)"
```

Expected: only `(end)` printed (no Python or test files in the branch diff vs main). If any `.py` or `tests/` path appears, M2 has overflowed scope — stop and reconcile before continuing.

- [ ] **Step 2: Lint gate**

```bash
python -m ruff check skills/bmad-story-automator/src/story_automator/
```

Expected: `All checks passed!` and exit 0.

- [ ] **Step 3: Format gate**

```bash
python -m ruff format --check skills/bmad-story-automator/src/story_automator/
```

Expected: zero files needing reformat, exit 0.

- [ ] **Step 4: Unit-test gate**

```bash
PYTHONPATH=skills/bmad-story-automator/src python -m unittest discover -s tests
```

Expected: `OK` at the end and exit 0. Test count and timing must match the previous `main`-HEAD run within reasonable variance.

- [ ] **Step 5: Coverage gate**

```bash
python -m coverage run --source=skills/bmad-story-automator/src/story_automator -m unittest discover -s tests && python -m coverage report -m --fail-under=85
```

Expected: coverage ≥ 85 %, exit 0.

- [ ] **Step 6: Import-allowlist gate (branch-diff form, robust on any base)**

```bash
git diff main...HEAD -- 'skills/bmad-story-automator/src/story_automator/' | grep -E '^\+(import|from) ' && echo "FAIL: branch adds Python imports" || echo "OK: no new imports"
```

Expected: `OK: no new imports`. M2's branch diff under `skills/.../story_automator/` is empty, so this trivially passes.

- [ ] **Step 7: Module-size gate**

```bash
find skills/bmad-story-automator/src/story_automator -name '*.py' -print0 \
  | xargs -0 -n1 sh -c 'lines=$(wc -l <"$1"); test "$lines" -le 500 || { echo "$1 has $lines lines (>500)"; exit 1; }' _
```

Expected: silent success, exit 0.

- [ ] **Step 8: No commit (verification-only task)**

---

### Task 12: Final M2 wrap — re-run every gate end-to-end and confirm the branch is PR-ready

**Files:**
- Read-only

- [ ] **Step 1: Re-run the full vocabulary gate script**

```bash
sh scripts/m11-vocabulary-gates.sh
echo "exit=$?"
```

Expected: every gate prints `PASS:` (Gate 6 may print `SKIP:` if no base ref is reachable). `exit=0`.

- [ ] **Step 2: Re-run the full `npm run verify` chain (belt-and-suspenders smoke-and-pack)**

```bash
npm run verify
```

Expected: exits 0. This catches packaging regressions even though M2 made no behavioral change.

- [ ] **Step 3: Summarize the M2 branch diff**

```bash
git log --oneline main..HEAD
git diff --stat main..HEAD
```

Expected `git log` output includes the M1 commits plus M2's new commits in this order (M1's commits first):

```text
… (M1 commits)
…  feat(m11): seed portable changelog-vocabulary gate script
…  feat(m11): add sub-heading isolation gate (REQ-09) to vocabulary gates
…  feat(m11): add contributor-guide gate (REQ-13) to vocabulary gates
…  feat(m11): add ordering-preservation gate (REQ-11) to vocabulary gates
…  feat(m11): add prose-immutability + whitespace gate (REQ-10) to vocabulary gates
…  feat(m11): add line-ending portability gate to vocabulary gates
…  docs(m11): add operator-facing changelog tag audit trail
…  chore(m11): expose vocabulary gate as npm run gates:vocab
```

Expected `git diff --stat main..HEAD` for the M2-specific files: `scripts/m11-vocabulary-gates.sh` (new, ~80 lines), `docs/changelog/AUDIT.md` (new, ~50 lines including the rationale table), `package.json` (+1 line). No `.py` file. No prose change to any historical changelog entry.

- [ ] **Step 4: Confirm the audit-trail document's row count still matches**

```bash
ROWS=$(grep -cE '^\| [0-9]+ \| `docs/changelog/' docs/changelog/AUDIT.md)
DATED=$(grep -hE '^##+ [0-9]{6}' docs/changelog/*.md | wc -l | tr -d ' ')
echo "rows=$ROWS dated=$DATED"
test "$ROWS" -eq "$DATED" && echo "OK: trail and headings match"
```

Expected: `rows=30 dated=30`, then `OK: trail and headings match`.

- [ ] **Step 5: No additional commit**

The branch is now ready for the finishing-a-development-branch flow (merge to main, open a PR, etc.). Hand off per operator preference.

---

## Self-review

Spec coverage:

- REQ-08 (every dated entry audited and tagged) — verified by Gate 1 (REQ-12 vocabulary-coverage). The M1 commits performed the tagging; Task 1 confirms it.
- REQ-09 (only dated headings tagged, sub-headings untouched) — Gate 3 in Task 4.
- REQ-10 (prose / bullets / files / QA notes unchanged) — Gate 6 in Task 7, with line-ending portability backstop in Task 8.
- REQ-11 (chronological order preserved, no entry moved/merged/split/deleted/re-dated) — Gate 5 in Task 6.
- REQ-12 (grep counts match) — Gate 1 in Task 3.
- NFR clean unified diff per file — Gate 6 (`git diff --check`).
- NFR no whitespace-only churn / no trailing whitespace / no line-ending changes — Gates 6 and 7.
- NFR audit reasoning recorded — Task 9's `docs/changelog/AUDIT.md` plus the existing M1 plan table.
- NFR vocabulary remains closed (no fifth tag) — Gate 2 (closed-vocabulary).
- Quality gates (vocabulary-coverage, closed-vocabulary, lint, format, unittest, coverage, import-allowlist, module-size, portability) — Gates 1–2 + Gate 4 in Task 5 + Task 11's six steps + Task 12 Step 2.

Placeholder scan: every step contains exact commands, exact file content, exact `old`/`new` edit strings, or exact expected output. No `TBD`, no `similar to`, no "add appropriate error handling."

Type consistency: gate numbering 1–7 is consistent across Tasks 3–8; the rationale-table row count of 30 is consistent across the inherited audit table, AUDIT.md, and Task 12 Step 4; the line-number signature in Task 6's Gate 5 matches the inherited audit table at the top of this plan.
