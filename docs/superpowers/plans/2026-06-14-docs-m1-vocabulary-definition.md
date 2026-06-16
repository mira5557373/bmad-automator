# M11 Changelog Vocabulary Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Introduce a closed four-tag scope vocabulary (`FULL`, `LITE`, `SKELETON`, `DEFERRED`) in `CONTRIBUTING.md` and retroactively tag every dated entry across the nine existing `docs/changelog/*.md` files, with zero Python source impact.

**Architecture:** This is a docs-only milestone. We add ~50-80 lines to `CONTRIBUTING.md` defining the vocabulary and insertion syntax (REQ-01..07, REQ-13) and edit exactly 30 dated heading lines across nine Markdown files (REQ-08..12). No new scripts, no new dependencies, no Python diff. Verification is performed by grep one-liners that already serve as the M11 quality gates and that run identically on Windows git-bash, WSL Ubuntu, and Linux CI.

**Tech Stack:** Markdown only. grep (BRE/ERE flavors that ship with Windows git-bash, WSL Ubuntu coreutils, and Linux CI coreutils). git for commits.

---

## Tag-assignment table (authoritative — copy each tag into the matching heading exactly)

The audit reasoning recorded here satisfies the NFR "audit reasoning for each retroactive tag assignment must be recorded in the M11 implementation plan." Each row lists: file, line number, current heading, chosen tag, and the one-line rationale based on what the entry's own Summary/Files/QA Notes describe.

| # | File | Line | Current heading | Tag | Rationale |
|---|------|------|-----------------|-----|-----------|
| 1 | `docs/changelog/260401.md` | 3 | `## 260412 - Pure Skill Install Layout` | `LITE` | Installer + runtime + smoke-test changes shipped together; no QA-Notes block records test runs, so depth is reduced. |
| 2 | `docs/changelog/260401.md` | 26 | `## 260401-22:47:02 - Prepare repository for open source release` | `LITE` | Repo-wiring entry (MIT, CI, smoke harness, contributor docs); QA Notes literally `N/A`. |
| 3 | `docs/changelog/260401.md` | 61 | `## 260414-10:30:57 - Harden tmux runtime for non-default shells` | `FULL` | New module plus dedicated tests; QA Notes run `compileall` and `unittest test_tmux_runtime`. |
| 4 | `docs/changelog/260401.md` | 85 | `## 260414-12:07:46 - Fix Claude runner sessions that stay open at the prompt after command completion` | `FULL` | Targeted fix plus regression test updates; QA Notes run `unittest test_tmux_runtime` and `compileall`. |
| 5 | `docs/changelog/260412.md` | 3 | `## 260412-02:41:53 - Migrate story automator installer to pure skill layout` | `LITE` | Large installer/runtime migration with bundled smoke updates; QA Notes `N/A`. |
| 6 | `docs/changelog/260412.md` | 34 | `## 260412-04:50:44 - Close review gaps in skill migration` | `LITE` | Follow-up review-gap fixes + smoke; QA Notes `N/A`. |
| 7 | `docs/changelog/260413.md` | 3 | `## 260413-09:14:32 - Restore verify-step retry contract` | `FULL` | Fix + unit + smoke; QA Notes run `unittest test_success_verifiers` and `smoke-test.sh`. |
| 8 | `docs/changelog/260413.md` | 27 | `## 260413-08:05:51 - Wire policy-backed success verifiers` | `LITE` | New registry shipped with unit coverage but QA Notes `N/A`. |
| 9 | `docs/changelog/260413.md` | 51 | `## 260413-09:26:29 - Tighten state policy compatibility helpers` | `LITE` | Compatibility fixes with tests; QA Notes `N/A`. |
| 10 | `docs/changelog/260413.md` | 77 | `## 260413-08:39:42 - Route create validation through shared verifier` | `FULL` | Helper added, smoke + tests updated; QA Notes run `npm run verify`. |
| 11 | `docs/changelog/260413.md` | 104 | `## 260413-08:34:25 - Harden success verifier review fixes` | `FULL` | Fix + tests + smoke; QA Notes run `npm run verify`. |
| 12 | `docs/changelog/260413.md` | 129 | `## 260413-11:35:00 - Verify packed npx install path` | `FULL` | Release-prep entry that re-pinned the publish smoke path; QA Notes run `npm run verify`. |
| 13 | `docs/changelog/260413.md` | 148 | `## 260413-03:41:50 - Stabilize Codex tmux review sessions` | `LITE` | Fix + smoke contract updates; QA Notes `N/A`. |
| 14 | `docs/changelog/260413.md` | 168 | `## 260413-05:03:47 - Add comprehensive automator documentation` | `LITE` | Docs-only rewrite; no test impact and no QA Notes block. |
| 15 | `docs/changelog/260413.md` | 195 | `## 260413-06:34:01 - Add JSON settings implementation plan` | `SKELETON` | Planning packet — directory tree of plan docs with no behavioral wiring, no tests. |
| 16 | `docs/changelog/260413.md` | 215 | `## 260413-07:29:16 - Add JSON runtime policy foundation` | `LITE` | Large impl + bundled data + tests, but QA Notes `N/A`. |
| 17 | `docs/changelog/260413.md` | 250 | `## 260413-07:55:28 - Harden runtime policy snapshot handling` | `LITE` | Snapshot/marker fixes + regression coverage; QA Notes `N/A`. |
| 18 | `docs/changelog/260413.md` | 277 | `## 260413-09:13:20 - Enforce snapshot-only resume semantics` | `LITE` | Fixes + tests + operator docs; QA Notes `N/A`. |
| 19 | `docs/changelog/260413.md` | 302 | `## 260413-11:00:47 - Harden parser runtime and validator compatibility` | `LITE` | Parser/validator hardening + tests; QA Notes `N/A`. |
| 20 | `docs/changelog/260413.md` | 330 | `## 260413-21:53:12 - Close state-summary and validator compatibility gaps` | `LITE` | Compatibility-gap fixes + regression coverage; QA Notes `N/A`. |
| 21 | `docs/changelog/260414.md` | 3 | `## 260414-21:51:35 - Harden snapshot and verifier review fixes` | `LITE` | Review-loop hardening + tests + docs; QA Notes `N/A`. |
| 22 | `docs/changelog/260415.md` | 3 | `## 260415-01:20:16 - Harden policy resume and review parsing` | `LITE` | Snapshot/parser fixes + regression coverage; QA Notes `N/A`. |
| 23 | `docs/changelog/260415.md` | 33 | `## 260415-06:47:15 - Harden tmux prompt and monitor contract failures` | `LITE` | Fail-closed fixes + regression coverage; QA Notes `N/A`. |
| 24 | `docs/changelog/260415.md` | 51 | `## 260415-07:54:52 - Tighten tmux monitor output verification` | `LITE` | Fixes + regressions for verifier outcome; QA Notes `N/A`. |
| 25 | `docs/changelog/260506.md` | 3 | `## 260506-19:21:58 - Support SKILL-only BMAD dependency installs` | `LITE` | Install + runtime relaxation + tests + docs; QA Notes `N/A`. |
| 26 | `docs/changelog/260508.md` | 3 | `## 260508-07:58:11 - Align Claude plugin marketplace metadata` | `LITE` | Metadata + docs polish; QA Notes `N/A`. |
| 27 | `docs/changelog/260508.md` | 25 | `## 260508-01:22:06 - Publish refreshed npx installer` | `LITE` | Pure version-bump release entry; QA Notes `N/A`. |
| 28 | `docs/changelog/260508.md` | 43 | `## 260508-01:17:06 - Repackage automator as self-contained skills` | `LITE` | Large repackage + docs + tests update; QA Notes `N/A`. |
| 29 | `docs/changelog/260517.md` | 3 | `## 260517 - Release Codex Runtime Support` | `FULL` | Release milestone with multi-root installer + tests + version bumps; QA Notes run `npm run verify`. |
| 30 | `docs/changelog/260519.md` | 3 | `## 260519 - Per-Task Model Selection` | `FULL` | Large impl + 26 new tests + 4 review passes; QA Notes run 229-test discover and smoke. |

Distribution: 8 `FULL`, 20 `LITE`, 1 `SKELETON`, 0 `DEFERRED`. The closed-vocabulary NFR allows a tag to be unused historically; `DEFERRED` is still defined in `CONTRIBUTING.md` for future entries.

---

### Task 1: Capture baseline RED state for the M11 grep gates

**Files:**
- Read-only: `docs/changelog/*.md`, `CONTRIBUTING.md`

This task confirms the gates fail before any change and records the expected GREEN target counts, so later tasks can detect drift.

- [ ] **Step 1: Count dated entry headings (target denominator for REQ-12)**

Run from repo root:

```bash
grep -hE '^##+ [0-9]{6}' docs/changelog/*.md | wc -l
```

Expected: `30`

- [ ] **Step 2: Count tagged dated headings (must currently be 0)**

```bash
grep -hE '^##+ [0-9]{6}.*\[(FULL|LITE|SKELETON|DEFERRED)\]' docs/changelog/*.md | wc -l
```

Expected: `0`

- [ ] **Step 3: Count CONTRIBUTING.md occurrences of each tag string as inline code (REQ-13 baseline)**

```bash
for tag in FULL LITE SKELETON DEFERRED; do printf '%s ' "$tag"; grep -c -F "\`$tag\`" CONTRIBUTING.md; done
```

Expected: each tag prints `0`.

- [ ] **Step 4: Closed-vocabulary inventory across dated headings (must currently be empty)**

```bash
grep -hE '^##+ [0-9]{6}' docs/changelog/*.md | grep -oE '\[[A-Z]{3,9}\]' | sort -u
```

Expected: empty output (no bracketed uppercase tokens on dated headings yet).

- [ ] **Step 5: Record baseline output**

There is nothing to commit in this task. Hold the four numbers above (`30`, `0`, four zeros, empty set) in the executor's working notes; later tasks compare against them.

---

### Task 2: Add the vocabulary section to `CONTRIBUTING.md`

**Files:**
- Modify: `CONTRIBUTING.md` (insert a new top-level section after the existing `## PR Notes` section, before `## Reporting Bugs`)

Implements REQ-01 through REQ-07, REQ-13, and the four "plain English" / "<100 added lines" / "uppercase ASCII tag" NFRs.

- [ ] **Step 1: Confirm the REQ-13 gate currently fails**

```bash
for tag in FULL LITE SKELETON DEFERRED; do grep -F -q "\`$tag\`" CONTRIBUTING.md || echo "missing: $tag"; done
```

Expected: prints `missing: FULL`, `missing: LITE`, `missing: SKELETON`, `missing: DEFERRED`.

- [ ] **Step 2: Insert the vocabulary section**

Open `CONTRIBUTING.md` and insert the block below as a new top-level section, placed after the existing `## PR Notes` section (currently ending at line 24) and before `## Reporting Bugs`. Add exactly one blank line above and one blank line below the new section to match the file's existing rhythm. The block below adds roughly 28 content lines plus blank-line padding, staying well under the 100-line NFR ceiling.

The block uses two nested code-fence layers (`````text` examples inside the section). The plan wraps the whole literal section in a four-backtick fence so the inner triple-backtick fences render correctly. **Copy the content between the four-backtick fences verbatim — do not change backtick counts.**

````markdown
## Changelog Scope Tags

Every new entry under `docs/changelog/` must carry exactly one scope tag from this closed four-tag vocabulary: `FULL`, `LITE`, `SKELETON`, or `DEFERRED`. The tag goes inside square brackets immediately after the timestamp and the hyphen on the entry's heading line, for example:

```text
## 260519-12:00:00 - [FULL] Title goes here
```

For entries without a time component the same rule applies after the bare date:

```text
## 260519 - [FULL] Title goes here
```

Exactly one tag is required per entry. PRs that add a changelog entry with no tag, with more than one tag, or with any tag string other than the four listed above must be rejected at review time. Tags apply only to the dated entry headings (level-two or level-three Markdown headings that begin with a six-digit date). Sub-section headings inside an entry such as `### Summary`, `### Added`, `### Changed`, `### Fixed`, `### Removed`, `### Files`, and `### QA Notes` must not carry tags.

The four tags mean:

- `FULL` — a change shipped with spec, implementation, tests, and verification all complete and passing every quality gate at merge time.
- `LITE` — a change shipped with implementation and tests but with reduced spec depth or deferred non-blocking polish, where every quality gate still passes at merge time.
- `SKELETON` — a change that lands structure or scaffolding only (for example a module stub or a directory tree) with no behavioral wiring and no test coverage requirement beyond import compilation.
- `DEFERRED` — a change recorded for traceability where the underlying work has been intentionally postponed to a later milestone. The entry must name the deferring milestone in its body, and no quality-gate enforcement applies to deferred entries.

The four tag strings are uppercase ASCII only so they are unambiguous under `grep -F`. The vocabulary is closed: adding a fifth tag requires a follow-up spec and is not permitted as a drive-by change.
````

- [ ] **Step 3: Re-run the REQ-13 gate, confirm it now passes**

```bash
for tag in FULL LITE SKELETON DEFERRED; do printf '%s ' "$tag"; grep -c -F "\`$tag\`" CONTRIBUTING.md; done
```

Expected: each tag line prints a count of at least `1`. The exact counts after this edit will be `FULL 1`, `LITE 1`, `SKELETON 1`, `DEFERRED 1` because each tag appears exactly once inside its definition bullet (REQ-13 demands "exactly once each as fenced inline code in the definition list").

- [ ] **Step 4: Confirm the added-line budget is within the NFR ceiling**

```bash
git diff --numstat -- CONTRIBUTING.md
```

Expected: the first column (added lines) is below `100`. The block above adds 55 content lines plus blank-line padding, so this passes comfortably.

- [ ] **Step 5: Confirm no whitespace-only churn or line-ending changes**

```bash
git diff --check -- CONTRIBUTING.md && git diff -- CONTRIBUTING.md | grep -E '^[+-]' | grep -E '\s+$' && echo "FAIL: trailing whitespace" || echo "OK: no trailing whitespace"
```

Expected: `git diff --check` exits 0 and the script prints `OK: no trailing whitespace`.

- [ ] **Step 6: Commit**

```bash
git add CONTRIBUTING.md
git commit --trailer "Generated-By: claude-opus-4-7" -m "docs(m11): define closed changelog scope-tag vocabulary"
```

---

### Task 3: Tag the four dated entries in `docs/changelog/260401.md`

**Files:**
- Modify: `docs/changelog/260401.md` lines 3, 26, 61, 85

- [ ] **Step 1: Confirm the file currently has 4 dated headings and 0 tagged headings**

```bash
grep -cE '^##+ [0-9]{6}' docs/changelog/260401.md
grep -cE '^##+ [0-9]{6}.*\[(FULL|LITE|SKELETON|DEFERRED)\]' docs/changelog/260401.md
```

Expected: `4` then `0`.

- [ ] **Step 2: Apply the four exact-string edits**

Use four separate `Edit` calls (one per heading) so each `old_string` stays uniquely matchable:

Edit 1:
- old: `## 260412 - Pure Skill Install Layout`
- new: `## 260412 - [LITE] Pure Skill Install Layout`

Edit 2:
- old: `## 260401-22:47:02 - Prepare repository for open source release`
- new: `## 260401-22:47:02 - [LITE] Prepare repository for open source release`

Edit 3:
- old: `## 260414-10:30:57 - Harden tmux runtime for non-default shells`
- new: `## 260414-10:30:57 - [FULL] Harden tmux runtime for non-default shells`

Edit 4:
- old: `## 260414-12:07:46 - Fix Claude runner sessions that stay open at the prompt after command completion`
- new: `## 260414-12:07:46 - [FULL] Fix Claude runner sessions that stay open at the prompt after command completion`

- [ ] **Step 3: Re-grep and confirm 4-and-4**

```bash
grep -cE '^##+ [0-9]{6}' docs/changelog/260401.md
grep -cE '^##+ [0-9]{6}.*\[(FULL|LITE|SKELETON|DEFERRED)\]' docs/changelog/260401.md
```

Expected: `4` then `4`.

- [ ] **Step 4: Confirm clean diff (no sub-section heading touched, no whitespace churn)**

```bash
git diff --check -- docs/changelog/260401.md
git diff --numstat -- docs/changelog/260401.md
git diff -U0 -- docs/changelog/260401.md | grep -E '^[+-][^+-]' | grep -vE '^[+-]## [0-9]{6}' && echo "FAIL: non-heading change detected" || echo "OK: only dated heading lines changed"
```

Expected: `git diff --check` exits 0; `git diff --numstat` prints `4\t4\tdocs/changelog/260401.md` (four lines added, four removed — one per dated heading); the third command prints `OK: only dated heading lines changed`.

- [ ] **Step 5: Commit**

```bash
git add docs/changelog/260401.md
git commit --trailer "Generated-By: claude-opus-4-7" -m "docs(m11): tag 260401.md changelog entries with scope vocabulary"
```

---

### Task 4: Tag the two dated entries in `docs/changelog/260412.md`

**Files:**
- Modify: `docs/changelog/260412.md` lines 3, 34

- [ ] **Step 1: Baseline-grep**

```bash
grep -cE '^##+ [0-9]{6}' docs/changelog/260412.md
grep -cE '^##+ [0-9]{6}.*\[(FULL|LITE|SKELETON|DEFERRED)\]' docs/changelog/260412.md
```

Expected: `2` then `0`.

- [ ] **Step 2: Apply edits**

Edit 1:
- old: `## 260412-02:41:53 - Migrate story automator installer to pure skill layout`
- new: `## 260412-02:41:53 - [LITE] Migrate story automator installer to pure skill layout`

Edit 2:
- old: `## 260412-04:50:44 - Close review gaps in skill migration`
- new: `## 260412-04:50:44 - [LITE] Close review gaps in skill migration`

- [ ] **Step 3: Re-grep**

```bash
grep -cE '^##+ [0-9]{6}' docs/changelog/260412.md
grep -cE '^##+ [0-9]{6}.*\[(FULL|LITE|SKELETON|DEFERRED)\]' docs/changelog/260412.md
```

Expected: `2` then `2`.

- [ ] **Step 4: Clean-diff check**

```bash
git diff --check -- docs/changelog/260412.md
git diff --numstat -- docs/changelog/260412.md
git diff -U0 -- docs/changelog/260412.md | grep -E '^[+-][^+-]' | grep -vE '^[+-]## [0-9]{6}' && echo "FAIL: non-heading change" || echo "OK"
```

Expected: exits 0; `git diff --numstat` prints `2\t2\tdocs/changelog/260412.md`; final command prints `OK`.

- [ ] **Step 5: Commit**

```bash
git add docs/changelog/260412.md
git commit --trailer "Generated-By: claude-opus-4-7" -m "docs(m11): tag 260412.md changelog entries with scope vocabulary"
```

---

### Task 5: Tag the fourteen dated entries in `docs/changelog/260413.md`

**Files:**
- Modify: `docs/changelog/260413.md` lines 3, 27, 51, 77, 104, 129, 148, 168, 195, 215, 250, 277, 302, 330

- [ ] **Step 1: Baseline-grep**

```bash
grep -cE '^##+ [0-9]{6}' docs/changelog/260413.md
grep -cE '^##+ [0-9]{6}.*\[(FULL|LITE|SKELETON|DEFERRED)\]' docs/changelog/260413.md
```

Expected: `14` then `0`.

- [ ] **Step 2: Apply the fourteen exact-string edits**

Each old_string is the unique current heading line; each new_string inserts `[TAG] ` immediately after the literal ` - `.

Edit 1: `## 260413-09:14:32 - Restore verify-step retry contract` → `## 260413-09:14:32 - [FULL] Restore verify-step retry contract`

Edit 2: `## 260413-08:05:51 - Wire policy-backed success verifiers` → `## 260413-08:05:51 - [LITE] Wire policy-backed success verifiers`

Edit 3: `## 260413-09:26:29 - Tighten state policy compatibility helpers` → `## 260413-09:26:29 - [LITE] Tighten state policy compatibility helpers`

Edit 4: `## 260413-08:39:42 - Route create validation through shared verifier` → `## 260413-08:39:42 - [FULL] Route create validation through shared verifier`

Edit 5: `## 260413-08:34:25 - Harden success verifier review fixes` → `## 260413-08:34:25 - [FULL] Harden success verifier review fixes`

Edit 6: `## 260413-11:35:00 - Verify packed npx install path` → `## 260413-11:35:00 - [FULL] Verify packed npx install path`

Edit 7: `## 260413-03:41:50 - Stabilize Codex tmux review sessions` → `## 260413-03:41:50 - [LITE] Stabilize Codex tmux review sessions`

Edit 8: `## 260413-05:03:47 - Add comprehensive automator documentation` → `## 260413-05:03:47 - [LITE] Add comprehensive automator documentation`

Edit 9: `## 260413-06:34:01 - Add JSON settings implementation plan` → `## 260413-06:34:01 - [SKELETON] Add JSON settings implementation plan`

Edit 10: `## 260413-07:29:16 - Add JSON runtime policy foundation` → `## 260413-07:29:16 - [LITE] Add JSON runtime policy foundation`

Edit 11: `## 260413-07:55:28 - Harden runtime policy snapshot handling` → `## 260413-07:55:28 - [LITE] Harden runtime policy snapshot handling`

Edit 12: `## 260413-09:13:20 - Enforce snapshot-only resume semantics` → `## 260413-09:13:20 - [LITE] Enforce snapshot-only resume semantics`

Edit 13: `## 260413-11:00:47 - Harden parser runtime and validator compatibility` → `## 260413-11:00:47 - [LITE] Harden parser runtime and validator compatibility`

Edit 14: `## 260413-21:53:12 - Close state-summary and validator compatibility gaps` → `## 260413-21:53:12 - [LITE] Close state-summary and validator compatibility gaps`

- [ ] **Step 3: Re-grep**

```bash
grep -cE '^##+ [0-9]{6}' docs/changelog/260413.md
grep -cE '^##+ [0-9]{6}.*\[(FULL|LITE|SKELETON|DEFERRED)\]' docs/changelog/260413.md
```

Expected: `14` then `14`.

- [ ] **Step 4: Confirm only `SKELETON` was used for entry 9 (the JSON-settings plan packet)**

```bash
grep -nE '\[SKELETON\]' docs/changelog/260413.md
```

Expected: exactly one line matching `## 260413-06:34:01 - [SKELETON] Add JSON settings implementation plan`.

- [ ] **Step 5: Clean-diff check**

```bash
git diff --check -- docs/changelog/260413.md
git diff --numstat -- docs/changelog/260413.md
git diff -U0 -- docs/changelog/260413.md | grep -E '^[+-][^+-]' | grep -vE '^[+-]## [0-9]{6}' && echo "FAIL: non-heading change" || echo "OK"
```

Expected: exits 0; `git diff --numstat` prints `14\t14\tdocs/changelog/260413.md`; final command prints `OK`.

- [ ] **Step 6: Commit**

```bash
git add docs/changelog/260413.md
git commit --trailer "Generated-By: claude-opus-4-7" -m "docs(m11): tag 260413.md changelog entries with scope vocabulary"
```

---

### Task 6: Tag the single dated entry in `docs/changelog/260414.md`

**Files:**
- Modify: `docs/changelog/260414.md` line 3

- [ ] **Step 1: Baseline-grep**

```bash
grep -cE '^##+ [0-9]{6}' docs/changelog/260414.md
grep -cE '^##+ [0-9]{6}.*\[(FULL|LITE|SKELETON|DEFERRED)\]' docs/changelog/260414.md
```

Expected: `1` then `0`.

- [ ] **Step 2: Apply the edit**

Edit 1: `## 260414-21:51:35 - Harden snapshot and verifier review fixes` → `## 260414-21:51:35 - [LITE] Harden snapshot and verifier review fixes`

- [ ] **Step 3: Re-grep**

```bash
grep -cE '^##+ [0-9]{6}' docs/changelog/260414.md
grep -cE '^##+ [0-9]{6}.*\[(FULL|LITE|SKELETON|DEFERRED)\]' docs/changelog/260414.md
```

Expected: `1` then `1`.

- [ ] **Step 4: Clean-diff check**

```bash
git diff --check -- docs/changelog/260414.md
git diff --numstat -- docs/changelog/260414.md
git diff -U0 -- docs/changelog/260414.md | grep -E '^[+-][^+-]' | grep -vE '^[+-]## [0-9]{6}' && echo "FAIL: non-heading change" || echo "OK"
```

Expected: exits 0; `git diff --numstat` prints `1\t1\tdocs/changelog/260414.md`; final command prints `OK`.

- [ ] **Step 5: Commit**

```bash
git add docs/changelog/260414.md
git commit --trailer "Generated-By: claude-opus-4-7" -m "docs(m11): tag 260414.md changelog entry with scope vocabulary"
```

---

### Task 7: Tag the three dated entries in `docs/changelog/260415.md`

**Files:**
- Modify: `docs/changelog/260415.md` lines 3, 33, 51

- [ ] **Step 1: Baseline-grep**

```bash
grep -cE '^##+ [0-9]{6}' docs/changelog/260415.md
grep -cE '^##+ [0-9]{6}.*\[(FULL|LITE|SKELETON|DEFERRED)\]' docs/changelog/260415.md
```

Expected: `3` then `0`.

- [ ] **Step 2: Apply the edits**

Edit 1: `## 260415-01:20:16 - Harden policy resume and review parsing` → `## 260415-01:20:16 - [LITE] Harden policy resume and review parsing`

Edit 2: `## 260415-06:47:15 - Harden tmux prompt and monitor contract failures` → `## 260415-06:47:15 - [LITE] Harden tmux prompt and monitor contract failures`

Edit 3: `## 260415-07:54:52 - Tighten tmux monitor output verification` → `## 260415-07:54:52 - [LITE] Tighten tmux monitor output verification`

- [ ] **Step 3: Re-grep**

```bash
grep -cE '^##+ [0-9]{6}' docs/changelog/260415.md
grep -cE '^##+ [0-9]{6}.*\[(FULL|LITE|SKELETON|DEFERRED)\]' docs/changelog/260415.md
```

Expected: `3` then `3`.

- [ ] **Step 4: Clean-diff check**

```bash
git diff --check -- docs/changelog/260415.md
git diff --numstat -- docs/changelog/260415.md
git diff -U0 -- docs/changelog/260415.md | grep -E '^[+-][^+-]' | grep -vE '^[+-]## [0-9]{6}' && echo "FAIL: non-heading change" || echo "OK"
```

Expected: exits 0; `git diff --numstat` prints `3\t3\tdocs/changelog/260415.md`; final command prints `OK`.

- [ ] **Step 5: Commit**

```bash
git add docs/changelog/260415.md
git commit --trailer "Generated-By: claude-opus-4-7" -m "docs(m11): tag 260415.md changelog entries with scope vocabulary"
```

---

### Task 8: Tag the single dated entry in `docs/changelog/260506.md`

**Files:**
- Modify: `docs/changelog/260506.md` line 3

- [ ] **Step 1: Baseline-grep**

```bash
grep -cE '^##+ [0-9]{6}' docs/changelog/260506.md
grep -cE '^##+ [0-9]{6}.*\[(FULL|LITE|SKELETON|DEFERRED)\]' docs/changelog/260506.md
```

Expected: `1` then `0`.

- [ ] **Step 2: Apply the edit**

Edit 1: `## 260506-19:21:58 - Support SKILL-only BMAD dependency installs` → `## 260506-19:21:58 - [LITE] Support SKILL-only BMAD dependency installs`

- [ ] **Step 3: Re-grep**

```bash
grep -cE '^##+ [0-9]{6}' docs/changelog/260506.md
grep -cE '^##+ [0-9]{6}.*\[(FULL|LITE|SKELETON|DEFERRED)\]' docs/changelog/260506.md
```

Expected: `1` then `1`.

- [ ] **Step 4: Clean-diff check**

```bash
git diff --check -- docs/changelog/260506.md
git diff --numstat -- docs/changelog/260506.md
git diff -U0 -- docs/changelog/260506.md | grep -E '^[+-][^+-]' | grep -vE '^[+-]## [0-9]{6}' && echo "FAIL: non-heading change" || echo "OK"
```

Expected: exits 0; `git diff --numstat` prints `1\t1\tdocs/changelog/260506.md`; final command prints `OK`.

- [ ] **Step 5: Commit**

```bash
git add docs/changelog/260506.md
git commit --trailer "Generated-By: claude-opus-4-7" -m "docs(m11): tag 260506.md changelog entry with scope vocabulary"
```

---

### Task 9: Tag the three dated entries in `docs/changelog/260508.md`

**Files:**
- Modify: `docs/changelog/260508.md` lines 3, 25, 43

- [ ] **Step 1: Baseline-grep**

```bash
grep -cE '^##+ [0-9]{6}' docs/changelog/260508.md
grep -cE '^##+ [0-9]{6}.*\[(FULL|LITE|SKELETON|DEFERRED)\]' docs/changelog/260508.md
```

Expected: `3` then `0`.

- [ ] **Step 2: Apply the edits**

Edit 1: `## 260508-07:58:11 - Align Claude plugin marketplace metadata` → `## 260508-07:58:11 - [LITE] Align Claude plugin marketplace metadata`

Edit 2: `## 260508-01:22:06 - Publish refreshed npx installer` → `## 260508-01:22:06 - [LITE] Publish refreshed npx installer`

Edit 3: `## 260508-01:17:06 - Repackage automator as self-contained skills` → `## 260508-01:17:06 - [LITE] Repackage automator as self-contained skills`

- [ ] **Step 3: Re-grep**

```bash
grep -cE '^##+ [0-9]{6}' docs/changelog/260508.md
grep -cE '^##+ [0-9]{6}.*\[(FULL|LITE|SKELETON|DEFERRED)\]' docs/changelog/260508.md
```

Expected: `3` then `3`.

- [ ] **Step 4: Clean-diff check**

```bash
git diff --check -- docs/changelog/260508.md
git diff --numstat -- docs/changelog/260508.md
git diff -U0 -- docs/changelog/260508.md | grep -E '^[+-][^+-]' | grep -vE '^[+-]## [0-9]{6}' && echo "FAIL: non-heading change" || echo "OK"
```

Expected: exits 0; `git diff --numstat` prints `3\t3\tdocs/changelog/260508.md`; final command prints `OK`.

- [ ] **Step 5: Commit**

```bash
git add docs/changelog/260508.md
git commit --trailer "Generated-By: claude-opus-4-7" -m "docs(m11): tag 260508.md changelog entries with scope vocabulary"
```

---

### Task 10: Tag the single dated entry in `docs/changelog/260517.md`

**Files:**
- Modify: `docs/changelog/260517.md` line 3

- [ ] **Step 1: Baseline-grep**

```bash
grep -cE '^##+ [0-9]{6}' docs/changelog/260517.md
grep -cE '^##+ [0-9]{6}.*\[(FULL|LITE|SKELETON|DEFERRED)\]' docs/changelog/260517.md
```

Expected: `1` then `0`.

- [ ] **Step 2: Apply the edit**

Edit 1: `## 260517 - Release Codex Runtime Support` → `## 260517 - [FULL] Release Codex Runtime Support`

- [ ] **Step 3: Re-grep**

```bash
grep -cE '^##+ [0-9]{6}' docs/changelog/260517.md
grep -cE '^##+ [0-9]{6}.*\[(FULL|LITE|SKELETON|DEFERRED)\]' docs/changelog/260517.md
```

Expected: `1` then `1`.

- [ ] **Step 4: Clean-diff check**

```bash
git diff --check -- docs/changelog/260517.md
git diff --numstat -- docs/changelog/260517.md
git diff -U0 -- docs/changelog/260517.md | grep -E '^[+-][^+-]' | grep -vE '^[+-]## [0-9]{6}' && echo "FAIL: non-heading change" || echo "OK"
```

Expected: exits 0; `git diff --numstat` prints `1\t1\tdocs/changelog/260517.md`; final command prints `OK`.

- [ ] **Step 5: Commit**

```bash
git add docs/changelog/260517.md
git commit --trailer "Generated-By: claude-opus-4-7" -m "docs(m11): tag 260517.md changelog entry with scope vocabulary"
```

---

### Task 11: Tag the single dated entry in `docs/changelog/260519.md`

**Files:**
- Modify: `docs/changelog/260519.md` line 3

- [ ] **Step 1: Baseline-grep**

```bash
grep -cE '^##+ [0-9]{6}' docs/changelog/260519.md
grep -cE '^##+ [0-9]{6}.*\[(FULL|LITE|SKELETON|DEFERRED)\]' docs/changelog/260519.md
```

Expected: `1` then `0`.

- [ ] **Step 2: Apply the edit**

Edit 1: `## 260519 - Per-Task Model Selection` → `## 260519 - [FULL] Per-Task Model Selection`

- [ ] **Step 3: Re-grep**

```bash
grep -cE '^##+ [0-9]{6}' docs/changelog/260519.md
grep -cE '^##+ [0-9]{6}.*\[(FULL|LITE|SKELETON|DEFERRED)\]' docs/changelog/260519.md
```

Expected: `1` then `1`.

- [ ] **Step 4: Clean-diff check**

```bash
git diff --check -- docs/changelog/260519.md
git diff --numstat -- docs/changelog/260519.md
git diff -U0 -- docs/changelog/260519.md | grep -E '^[+-][^+-]' | grep -vE '^[+-]## [0-9]{6}' && echo "FAIL: non-heading change" || echo "OK"
```

Expected: exits 0; `git diff --numstat` prints `1\t1\tdocs/changelog/260519.md`; final command prints `OK`.

- [ ] **Step 5: Commit**

```bash
git add docs/changelog/260519.md
git commit --trailer "Generated-By: claude-opus-4-7" -m "docs(m11): tag 260519.md changelog entry with scope vocabulary"
```

---

### Task 12: Run the four M11 vocabulary gates GREEN

**Files:**
- Read-only: `docs/changelog/*.md`, `CONTRIBUTING.md`

This task is the green-mirror of Task 1 and exercises every M11-specific quality gate from the spec.

- [ ] **Step 1: REQ-12 vocabulary-coverage gate**

```bash
DATED=$(grep -hE '^##+ [0-9]{6}' docs/changelog/*.md | wc -l)
TAGGED=$(grep -hE '^##+ [0-9]{6}.*\[(FULL|LITE|SKELETON|DEFERRED)\]' docs/changelog/*.md | wc -l)
echo "dated=$DATED tagged=$TAGGED"
test "$DATED" -eq "$TAGGED" -a "$DATED" -eq 30
```

Expected: prints `dated=30 tagged=30` and exits 0.

- [ ] **Step 2: Closed-vocabulary gate (only the four allowed tokens may appear in brackets on dated headings)**

```bash
grep -hE '^##+ [0-9]{6}' docs/changelog/*.md | grep -oE '\[[A-Z]{3,9}\]' | sort -u
```

Expected: exactly four lines in this order:

```text
[DEFERRED]
[FULL]
[LITE]
[SKELETON]
```

If `[DEFERRED]` is absent because no historical entry uses it, the expected output is the three-line set `[FULL]`, `[LITE]`, `[SKELETON]` instead — both outcomes pass the gate because the gate's text is "returns only the four tokens ... and no others" (subset of the closed set is allowed). For the current audit-result distribution (8/20/1/0) the three-line output is the expected reality.

- [ ] **Step 3: Contributor-guide gate (REQ-13)**

```bash
for tag in FULL LITE SKELETON DEFERRED; do printf '%s ' "$tag"; grep -c -F "\`$tag\`" CONTRIBUTING.md; done
```

Expected: each tag prints a count of `1`.

- [ ] **Step 4: REQ-09 sub-heading isolation**

Confirm that every tagged heading is also a dated heading — i.e., no sub-section heading received a tag. A non-zero match here is a hard failure of REQ-09. The inverse check below is robust to any sub-heading wording (it does not depend on hardcoding the sub-section names).

```bash
grep -hE '^##+' docs/changelog/*.md | grep -E '\[(FULL|LITE|SKELETON|DEFERRED)\]' | grep -vE '^##+ [0-9]{6}' && echo "FAIL: a non-dated heading carries a tag" || echo "OK: only dated headings tagged"
```

Expected: prints `OK: only dated headings tagged`.

- [ ] **Step 5: REQ-11 ordering preservation**

The retroactive audit must not have moved any entry. Re-check that the dated-heading line numbers per file match the plan's authoritative table:

```bash
for f in docs/changelog/*.md; do printf '%s\n' "$f"; grep -nE '^##+ [0-9]{6}' "$f" | awk -F: '{print "  line " $1}'; done
```

Expected: line numbers match exactly the line-number column in the plan's authoritative tag-assignment table (4 entries in 260401.md at 3/26/61/85; 2 in 260412.md at 3/34; etc.).

- [ ] **Step 6: No commit (verification only)**

This task only reads; no commit is produced.

---

### Task 13: Confirm the inherited Python quality gates remain GREEN (no Python diff)

**Files:**
- Read-only: `skills/bmad-story-automator/`, `tests/`

M11 ships no Python changes, so all six inherited Python gates must keep their previous statuses without any new work. This task is a guard against accidental drift.

- [ ] **Step 1: Confirm no Python or test file changed in the M11 branch**

```bash
git diff --name-only main...HEAD | grep -E '\.(py)$' && echo "FAIL: Python diff detected" || echo "OK: no Python diff"
git diff --name-only main...HEAD | grep -E '^tests/' && echo "FAIL: tests diff detected" || echo "OK: no tests diff"
```

Expected: both lines print `OK`.

- [ ] **Step 2: Lint gate**

```bash
python -m ruff check skills/bmad-story-automator/src/story_automator/
```

Expected: zero violations and exit 0.

- [ ] **Step 3: Format gate**

```bash
python -m ruff format --check skills/bmad-story-automator/src/story_automator/
```

Expected: zero files needing reformat and exit 0.

- [ ] **Step 4: Unit-test gate**

```bash
PYTHONPATH=skills/bmad-story-automator/src python -m unittest discover -s tests
```

Expected: same suite as `main` HEAD, zero new failures or errors.

- [ ] **Step 5: Coverage gate**

```bash
python -m coverage run --source=skills/bmad-story-automator/src/story_automator -m unittest discover -s tests && python -m coverage report -m --fail-under=85
```

Expected: exits 0 (coverage at or above 85 percent).

- [ ] **Step 6: Import-allowlist gate**

The spec's wording is "a grep across `skills/bmad-story-automator/src/story_automator/` for **new** imports beyond stdlib plus `filelock` and `psutil` returns zero matches." Since M11 ships no Python diff at all, "new" reduces to "added by this branch relative to `main`," which is trivially zero. The diff-based check below is portable and never false-fails on legitimate pre-existing imports:

```bash
git diff main...HEAD -- 'skills/bmad-story-automator/src/story_automator/' | grep -E '^\+(import|from) ' && echo "FAIL: branch adds Python imports" || echo "OK: no new imports added by M11"
```

Expected: prints `OK: no new imports added by M11` and the preceding grep finds zero lines (because the M11 diff under `skills/bmad-story-automator/src/story_automator/` is empty). If the branch name differs (for example a worktree branch), substitute the actual base ref for `main`.

- [ ] **Step 7: Module-size gate**

```bash
find skills/bmad-story-automator/src/story_automator -name '*.py' -print0 | xargs -0 -n1 sh -c 'lines=$(wc -l <"$1"); test "$lines" -le 500 || { echo "$1 has $lines lines (>500)"; exit 1; }' _
```

Expected: silent success and exit 0.

- [ ] **Step 8: No commit (verification only)**

---

### Task 14: Verify portability across Windows git-bash, WSL Ubuntu, and Linux CI

**Files:**
- Read-only

The non-functional requirement "All quality gates run on Windows git-bash, WSL Ubuntu, and Linux CI without modification" is verified by sticking to POSIX `grep -E`, `wc`, `sort`, `awk`, `find`, and `xargs` — all of which ship with all three environments. This task spot-checks the most failure-prone behaviors.

- [ ] **Step 1: Confirm no carriage-return contamination on tagged heading lines**

CRLF line endings on Windows can break `^...$` anchors with some greps. Confirm the touched files stay LF-only on disk:

```bash
for f in CONTRIBUTING.md docs/changelog/*.md; do
  if grep -lU $'\r' "$f" >/dev/null 2>&1; then echo "FAIL: $f has CRLF"; else echo "OK: $f LF-only"; fi
done
```

Expected: every file prints `OK: ... LF-only`. (`git config core.autocrlf` may rewrite endings on checkout; if a `FAIL` appears, fix the working-tree file by re-saving with LF endings and re-stage. `.gitattributes` or per-file `text eol=lf` is also acceptable, but introducing new project-wide config is outside M11 scope — fix per-file only if the existing repo state already prefers LF.)

- [ ] **Step 2: Confirm `grep -E` accepts the M11 regexes under Windows git-bash**

If executing on Windows git-bash specifically, run the same gates as Task 12 Step 1 inside a fresh bash subshell:

```bash
bash -c "grep -hE '^##+ [0-9]{6}' docs/changelog/*.md | wc -l"
```

Expected: `30`. If executing on Linux or WSL, this step is implicitly already covered by Task 12 — re-run only when an actual Windows environment is available.

- [ ] **Step 3: No commit (verification only)**

---

### Task 15: Final M11 wrap and PR-prep verification

**Files:**
- Read-only

- [ ] **Step 1: Full-branch summary diff**

```bash
git log --oneline main..HEAD
git diff --stat main..HEAD
```

Expected: twelve commits — one CLAUDE.md commit (Phase A), one M11-spec commit (already on the branch before Phase A started), one M11 plan commit (Phase A), one CONTRIBUTING.md vocabulary commit (Task 2), and nine changelog-tag commits (Tasks 3–11, one per file). If the spec commit was made earlier on the branch and is already counted in `git log main..HEAD`, the total will be twelve; if the spec lives on `main` already, the total will be eleven. The `git diff --stat` output must show: `CLAUDE.md` (~55 lines), `CONTRIBUTING.md` (≤100 added lines), the plan and spec files under `docs/superpowers/`, and exactly nine Markdown files under `docs/changelog/`. No `.py` file may appear.

- [ ] **Step 2: Verify the four M11 gates one final time**

Re-run Task 12 steps 1, 2, 3, and 4 verbatim. All must pass.

- [ ] **Step 3: Smoke-run the existing `npm run verify` chain (no behavior change expected)**

```bash
npm run verify
```

Expected: exits 0. This is a belt-and-suspenders confirmation that the docs-only change has not perturbed the install + smoke pipeline.

- [ ] **Step 4: No additional commit**

The plan is complete; no further code or doc commits are produced by this task. Hand off to whichever finishing-a-development-branch flow the operator prefers (merge to main, open a PR, etc.).
