# Compat Wave 0: Pre-Flight — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Lock the floor before any Wave 1 module work begins. Commit the existing audit corpus so deep-review artefacts have a stable git history, capture the current test baseline so every Wave can prove "no regression" against a concrete number, and (best-effort) pin the `external/*` reference submodules so contract verification cannot silently drift mid-roadmap.

**Architecture:** This Wave touches no Python code. It is pure repo hygiene executed before Wave 1. Three independent tasks (Task 1, Task 2, Task 3) land as three sequential commits on `bma-d/integration-all`; the milestone closes with the `compat-w0-pre-flight` tag.

**Tech Stack:** git, plain text, JSON. No Python imports change. No test files change. No telemetry, no audit-event, no profile, no policy code is touched.

## Global Constraints

- **No Python changes.** This Wave does not import, modify, or add modules under `skills/bmad-story-automator/src/story_automator/`. It does not modify `tests/`.
- **Do NOT touch `core/telemetry_events.py`.** Trivially honoured — no Python edits at all in this Wave.
- **500-LOC soft limit per Python module.** N/A — no Python edits in this Wave.
- **Conventional Commits + `Generated-By:` trailer on every commit.** Three commits in this Wave; each must carry `Generated-By: claude-opus-4-7`.
- **No new Python deps.** Trivially honoured.
- **No trailing whitespace, whitespace-only churn, or line-ending changes** in any edited file.
- **Cross-platform paths**: any baseline text file uses LF line endings; submodule SHAs use full 40-char hex.
- **Baseline = 3124 tests passing** (today's `unittest discover` count on `bma-d/integration-all`). Task 2 freezes that number as the recorded floor; Wave 1 and later Waves must demonstrate `>= 3124` and never regress.
- **Task 3 may defer.** Pinning all seven `external/*` submodules + adding a CI assertion is allowed to be marked DEFERRED if it would require a non-trivial CI rewrite; in that case the deferral note must explain why and point at the existing `git submodule status` SHAs already captured in the spec.

## File Structure

**New files:**
- `docs/audit/baseline-tests.txt` — frozen baseline test count + invocation + SHA at time of capture (~10 LOC)

**Modified files (Task 3 only, if not deferred):**
- `.gitmodules` — add `branch = <sha-or-tag>` lines per submodule, OR leave untouched if the submodule SHAs are already what they need to be at HEAD (gitlinks already pin SHAs; the explicit branch pin is belt-and-braces).
- `.github/workflows/ci.yml` — add an `external-pins` job that fails if `git submodule status` reports any uncommitted SHA drift on PRs.

**Untouched (explicit):** every file under `skills/`, every file under `tests/`, every file under `docs/changelog/`, every file under `docs/superpowers/specs/`, every file outside `docs/audit/` and `.github/`.

**Already-untracked artefacts to commit (Task 1):**
- `docs/audit/2026-06-19/` — full deep-review corpus (`coverage.json`, `coverage-branch.json`, `index.md`, `out-of-scope-observations.md`, `roadmap.md`, `self-check.md`, `findings/*.md`, `skeptics/*`)
- `docs/audit/trailer-corrigenda-2026-06-21.md` — single-page corrigenda doc from the trailer cleanup pass

---

### Task 1: Commit the audit corpus

**Files:**
- Stage: every untracked file under `docs/audit/`

**Interfaces:** none — this is a pure `git add` + `git commit` step. The audit corpus already exists on disk; this task only moves it from untracked to tracked.

**Pre-conditions:**
- Current branch is `bma-d/integration-all`.
- `git status --short docs/audit/` shows untracked entries (verified at plan time: `?? docs/audit/`, `?? Date:`).
- Working tree under `skills/` and `tests/` has no unrelated dirty changes that would get folded into this commit.

- [ ] **Step 1: Inspect untracked audit contents**

Run:

```bash
git status --short docs/audit/
ls docs/audit/
ls docs/audit/2026-06-19/
```

Expected: a `2026-06-19/` directory plus the `trailer-corrigenda-2026-06-21.md` page. Do NOT commit any stray file named `Date:` if `git status` shows one — that is a shell artefact, not a real audit artefact; delete it first with `rm -- 'Date:'` from the repo root if present.

- [ ] **Step 2: Stage only `docs/audit/`**

Explicit path so nothing outside the audit tree is folded in:

```bash
git add docs/audit/
git status --short
```

Expected: only files under `docs/audit/` listed as `A`. If any file under `skills/` or `tests/` is staged, run `git restore --staged <path>` until the diff is audit-only.

- [ ] **Step 3: Verify the diff is documentation only**

```bash
git diff --cached --stat docs/audit/ | tail -20
git diff --cached --name-only | grep -vE '^docs/audit/'
```

Expected: the second command prints nothing. If it prints any path, unstage that path before committing.

- [ ] **Step 4: Commit**

```bash
git commit -m "$(cat <<'EOF'
docs(audit): commit 2026-06-19 deep-review corpus + trailer corrigenda

Moves the previously-untracked deep-review audit corpus (findings,
skeptics, coverage JSONs, index, roadmap, self-check, out-of-scope
observations) and the 2026-06-21 trailer corrigenda page into git so
later Waves can cite specific findings by stable path/SHA.

No code, test, or schema changes — pure docs landing.

Generated-By: claude-opus-4-7
EOF
)"
```

- [ ] **Step 5: Verify the commit landed clean**

```bash
git log -1 --stat | head -30
git status --short docs/audit/
```

Expected: HEAD is the new commit; `docs/audit/` is fully tracked (no `??` lines).

---

### Task 2: Capture the baseline test count

**Files:**
- Create: `docs/audit/baseline-tests.txt`

**Interfaces:** none — a single plain-text artefact. Read-only for every later Wave; each Wave's close-out test sweep must compare its observed count against this file's recorded number.

**Pre-conditions:**
- Task 1 commit is on HEAD.
- Full test suite passes locally on `bma-d/integration-all` (verified at plan time: `Ran 3124 tests in 48.074s — OK (skipped=2)`).

- [ ] **Step 1: Run the full suite and capture the tail**

Run:

```bash
PYTHONPATH=skills/bmad-story-automator/src python3 -m unittest discover -s tests 2>/tmp/baseline-tests.raw
tail -5 /tmp/baseline-tests.raw
```

Expected: the tail shows a line `Ran NNNN tests in <seconds>s` followed by `OK` (skips allowed). Record the `NNNN` integer — this is the locked baseline. At plan time the expected number is **3124** with **2 skipped**; if a different number is observed, use the observed number and note the delta in the artefact.

- [ ] **Step 2: Capture the head commit SHA + branch**

```bash
git rev-parse HEAD
git rev-parse --abbrev-ref HEAD
```

Record both. These pin the baseline to a specific tree state so later Waves can reproduce.

- [ ] **Step 3: Write the baseline artefact**

Create `docs/audit/baseline-tests.txt` with content of this exact shape (replace `<sha>` and `<count>` and `<skipped>`):

```
# Wave 0 pre-flight baseline
# Captured on bma-d/integration-all at <sha>
# Invocation:
#   PYTHONPATH=skills/bmad-story-automator/src python3 -m unittest discover -s tests
#
# Expected at plan time: 3124 tests, 2 skipped.
# Any later Wave MUST observe >= this count. Regressions block the Wave's tag.

tests_total = <count>
tests_skipped = <skipped>
captured_sha = <sha>
captured_branch = bma-d/integration-all
captured_date = 2026-06-21
```

No trailing whitespace on any line. LF line endings only. Final newline at end of file.

- [ ] **Step 4: Sanity-check the artefact**

```bash
cat docs/audit/baseline-tests.txt
grep -n ' $' docs/audit/baseline-tests.txt || echo "no trailing whitespace"
file docs/audit/baseline-tests.txt
```

Expected: `file` reports `ASCII text`; the `grep` prints `no trailing whitespace`; the integer on `tests_total =` matches what you observed in Step 1.

- [ ] **Step 5: Stage and commit**

```bash
git add docs/audit/baseline-tests.txt
git diff --cached --name-only
git diff --cached --name-only | grep -vE '^docs/audit/baseline-tests\.txt$'
```

The third command must print nothing.

```bash
git commit -m "$(cat <<'EOF'
docs(audit): freeze Wave-0 baseline test count

Captures the test-suite floor on bma-d/integration-all so every later
Wave can prove "no regression" against a concrete number rather than a
remembered count. Records invocation, total, skipped, and source SHA.

Expected baseline: 3124 tests, 2 skipped.

Generated-By: claude-opus-4-7
EOF
)"
```

- [ ] **Step 6: Verify**

```bash
git log -1 --stat | head -10
```

Expected: a single one-file commit adding `docs/audit/baseline-tests.txt`.

---

### Task 3: Pin external/* submodule SHAs (defer if non-trivial)

**Files:**
- Optionally modify: `.gitmodules` — add explicit `branch = <sha>` per submodule
- Optionally modify: `.github/workflows/ci.yml` — add an `external-pins` job that fails on drift
- OR create: `docs/audit/wave-0-task-3-deferred.md` recording the deferral and the SHAs to pin in follow-up

**Interfaces:** none. Either CI gains a drift-detection job, or a deferral note is committed pointing at the existing gitlink SHAs.

**Pre-conditions:**
- Task 1 and Task 2 commits are on HEAD.
- `git submodule status` reports the current pinned SHAs (gitlinks). At plan time those are:

| submodule | SHA | tag-ish |
| --- | --- | --- |
| external/BMAD-METHOD | `9d5739d9920bfe892e683a750e388996306082fd` | v6.8.0-20-g9d5739d9 |
| external/bmad-auto | `c1b4edd46211013eb4986cad439d1302924b1e8a` | v0.6.1 |
| external/bmad-automator-upstream | `f332173a692ffbabb24734c31dedadfcf78b9ed1` | v1.15.0-23-gf332173 |
| external/bmad-method-sample-data | `3aadf7a6a35e8c0298b14bcbd77a264cf3e0ee98` | heads/main |
| external/bmad-method-test-architecture-enterprise | `8734d51f24071ddbcb3617390b5fcddb4128ef77` | v1.19.0 |
| external/bmad-method-wds-expansion | `cc16f09fcfab26d35635af1491f36a38a8431c8d` | v0.4.3 |
| external/superpower-workflow | `e5c6d062e9c7c983e54fc264455a1e11ca30198b` | v1.4.0-2-ge5c6d06 |

The gitlinks themselves already pin the SHAs; the question is whether to add a CI assertion that those gitlinks have not drifted in an open PR.

- [ ] **Step 1: Decide path A (implement) vs path B (defer)**

Inspect `.github/workflows/ci.yml`. If adding a new job is straightforward (one extra `jobs.external-pins` block that runs `git submodule status` and `git diff --quiet HEAD -- external/`), proceed with path A. Otherwise, take path B.

The bar for "non-trivial" is: any CI change that would require modifying the existing matrix, adding new secrets, or touching how `actions/checkout@v6` runs (`submodules: true` flag, recursive checkout, etc.). If you would need to enable submodule checkout in CI just to run the assertion, **that counts as non-trivial — defer.**

- [ ] **Step 2a (Path A — implement): record the SHA table in `.gitmodules` as comments**

Open `.gitmodules`. For each `[submodule "external/<name>"]` block, append a comment line immediately after the `url = ` line:

```
[submodule "external/BMAD-METHOD"]
	path = external/BMAD-METHOD
	url = https://github.com/bmad-code-org/BMAD-METHOD
	# pinned-at = 9d5739d9920bfe892e683a750e388996306082fd  # v6.8.0-20-g9d5739d9
```

Do NOT add `branch = <sha>` — git submodule does not accept a SHA in the `branch` field (it accepts a branch name, not a commit). The comment is the human-readable pin record; the gitlink itself is the real pin.

Repeat for all seven submodules listed in the pre-conditions table.

Verify:

```bash
git diff .gitmodules
grep '^	# pinned-at' .gitmodules | wc -l
```

Expected: `7`.

- [ ] **Step 3a (Path A — implement): add the CI drift-detection job**

Append a new job to `.github/workflows/ci.yml` under `jobs:`. Place it AFTER the `verify` job; do NOT modify the existing `verify` matrix.

```yaml
  external-pins:
    name: external/* submodule pins
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v6
        with:
          submodules: false
      - name: Assert pinned-at comments match gitlink SHAs
        shell: bash
        run: |
          set -euo pipefail
          fail=0
          while read -r path sha; do
            expected=$(awk -v p="$path" '
              $1 == "[submodule" && $0 ~ p { in_block=1; next }
              in_block && /^\[submodule/ { in_block=0 }
              in_block && /pinned-at/ { print $4; exit }
            ' .gitmodules)
            if [[ -z "$expected" ]]; then
              echo "::error::no pinned-at comment for $path"
              fail=1
              continue
            fi
            if [[ "$sha" != "$expected" ]]; then
              echo "::error::$path drifted: gitlink=$sha pinned-at=$expected"
              fail=1
            fi
          done < <(git ls-tree HEAD external/ | awk '$2 == "commit" { print $4, $3 }')
          exit "$fail"
```

Verify with `actionlint` if available, otherwise hand-inspect.

- [ ] **Step 4a (Path A — implement): commit**

```bash
git add .gitmodules .github/workflows/ci.yml
git diff --cached --name-only | grep -vE '^(\.gitmodules|\.github/workflows/ci\.yml)$'
```

Third command must print nothing.

```bash
git commit -m "$(cat <<'EOF'
ci(external): pin external/* submodule SHAs via pinned-at comments + CI assertion

Adds a human-readable pinned-at comment per submodule in .gitmodules (the
gitlink itself is the real pin; the comment is the audit trail) and a new
external-pins CI job that fails if any gitlink SHA drifts from its
pinned-at comment. Prevents silent contract-verification drift mid-Wave.

Generated-By: claude-opus-4-7
EOF
)"
```

- [ ] **Step 2b (Path B — defer): write the deferral note**

Create `docs/audit/wave-0-task-3-deferred.md`:

```markdown
# Wave 0 Task 3 — deferred

Status: DEFERRED to a later Wave (target: Wave 1 close-out or Wave 2 kickoff).

## Why deferred

Adding a CI drift-detection job for external/* gitlinks would require
enabling submodule checkout in the existing ci.yml matrix, which is a
non-trivial change to the Wave-0 floor. Wave 0's purpose is to lock the
floor without touching CI plumbing — that work belongs in a focused
later commit.

## What protects us in the meantime

The gitlinks themselves already pin each external/* submodule to a
specific commit. A PR cannot silently re-target a submodule without
producing a visible diff against the existing gitlink. The "silent
drift" risk is therefore bounded by reviewer diligence on the gitlink
diff, not by absence of CI enforcement.

## SHAs to pin when un-deferred

| submodule | SHA | tag-ish |
| --- | --- | --- |
| external/BMAD-METHOD | 9d5739d9920bfe892e683a750e388996306082fd | v6.8.0-20-g9d5739d9 |
| external/bmad-auto | c1b4edd46211013eb4986cad439d1302924b1e8a | v0.6.1 |
| external/bmad-automator-upstream | f332173a692ffbabb24734c31dedadfcf78b9ed1 | v1.15.0-23-gf332173 |
| external/bmad-method-sample-data | 3aadf7a6a35e8c0298b14bcbd77a264cf3e0ee98 | heads/main |
| external/bmad-method-test-architecture-enterprise | 8734d51f24071ddbcb3617390b5fcddb4128ef77 | v1.19.0 |
| external/bmad-method-wds-expansion | cc16f09fcfab26d35635af1491f36a38a8431c8d | v0.4.3 |
| external/superpower-workflow | e5c6d062e9c7c983e54fc264455a1e11ca30198b | v1.4.0-2-ge5c6d06 |

## When un-deferring

Follow path A in `docs/superpowers/plans/2026-06-21-compat-w0-pre-flight.md`
Task 3: add `# pinned-at = <sha>` comments to .gitmodules and the
`external-pins` job to .github/workflows/ci.yml.
```

No trailing whitespace; LF line endings; final newline.

- [ ] **Step 3b (Path B — defer): commit the deferral note**

```bash
git add docs/audit/wave-0-task-3-deferred.md
git diff --cached --name-only | grep -vE '^docs/audit/wave-0-task-3-deferred\.md$'
```

Second command must print nothing.

```bash
git commit -m "$(cat <<'EOF'
docs(audit): defer Wave-0 Task 3 (external/* CI pin assertion)

Records the deferral of the submodule drift-detection CI job and the
SHA table to pin when un-deferred. The gitlinks themselves already pin
each external/* to a specific commit; CI enforcement is a Wave-1+
follow-up that requires enabling submodule checkout in the matrix.

Generated-By: claude-opus-4-7
EOF
)"
```

- [ ] **Step 4: Verify the chosen path landed**

```bash
git log -3 --oneline
```

Expected: three commits on HEAD in this Wave (Task 1, Task 2, Task 3-A or Task 3-B), each carrying the `Generated-By: claude-opus-4-7` trailer.

---

### Task 4: Milestone close-out — full test sweep + tag

**Files:** none — verification + tag only.

**Interfaces:** none.

**Pre-conditions:**
- Three Wave 0 commits are on HEAD (Task 1, Task 2, Task 3-A or Task 3-B).
- Working tree is clean (`git status --short` empty except for any out-of-scope untracked files that pre-existed the Wave).

- [ ] **Step 1: Re-run the full suite to confirm no regression**

```bash
PYTHONPATH=skills/bmad-story-automator/src python3 -m unittest discover -s tests 2>/tmp/wave-0-close.raw
tail -3 /tmp/wave-0-close.raw
```

Expected: the tail line `Ran NNNN tests` reports the same `NNNN` recorded in `docs/audit/baseline-tests.txt`. If the number differs (in either direction), STOP — the Wave's commits introduced a regression and must be diagnosed before tagging.

- [ ] **Step 2: Verify the trailer on every Wave-0 commit**

```bash
git log --pretty='%H %s%n%(trailers:key=Generated-By)' HEAD~3..HEAD
```

Expected: every commit shows `Generated-By: claude-opus-4-7`. If any commit is missing the trailer, do NOT proceed to tag — fix forward by adding a follow-up commit that documents the omission, or re-commit if the user explicitly authorizes amending; otherwise the milestone tag goes on the last commit-with-trailer.

- [ ] **Step 3: Confirm `core/telemetry_events.py` is untouched**

```bash
git diff HEAD~3..HEAD -- skills/bmad-story-automator/src/story_automator/core/telemetry_events.py
git diff HEAD~3..HEAD -- skills/
git diff HEAD~3..HEAD -- tests/
```

Expected: all three commands print nothing. If anything appears, Wave 0 has overstepped — investigate before tagging.

- [ ] **Step 4: Tag the milestone**

```bash
git tag -a compat-w0-pre-flight -m "Compat Wave 0: pre-flight floor locked

- Audit corpus committed (Task 1)
- Baseline test count frozen at <count> tests (Task 2)
- external/* SHA pin path: A (CI assertion) | B (deferred)
"
git tag --list compat-w0-pre-flight
```

Replace `<count>` with the integer from `docs/audit/baseline-tests.txt`. Pick the correct path A/B line in the tag message.

- [ ] **Step 5: Show final state**

```bash
git log --oneline HEAD~3..HEAD
git tag --list | grep -E '^(compat|phase|wave)' | sort
```

Expected: the three Wave 0 commits visible; `compat-w0-pre-flight` listed alongside the existing `phase-0..phase-3` and `phases-4-6-deferred` tags.

---

## Self-Review

**1. Spec coverage:** Three pre-flight tasks named in the spec are covered: (1) commit `docs/audit/` — Task 1; (2) capture baseline test count — Task 2; (3) pin external/* submodule SHAs + CI assertion — Task 3 with explicit defer path. Close-out (Task 4) ensures the floor is provably no-regression before the tag lands.

**2. Placeholder scan:** No TBD, TODO, "add appropriate", or description-only steps. Each task gives the exact commands, the exact file content (or the exact alternative path), and the exact verification command. Baseline count cited from the live suite: 3124 tests, 2 skipped, captured against `bma-d/integration-all` at plan time.

**3. Type consistency:** No Python types in this Wave. All artefacts are plain text or YAML. Branch is `bma-d/integration-all` throughout. Tag is `compat-w0-pre-flight` (matches the convention recorded in CLAUDE.md: "Each milestone adds tag compat-mNN-slug").

**4. Guardrail compliance:** Zero Python edits; zero touches to `core/telemetry_events.py`, `core/audit.py`, `core/atomic_io.py`, or any file under `skills/` or `tests/`. Zero new Python deps. Every commit carries the `Generated-By: claude-opus-4-7` trailer. No `--no-verify`, no `--amend`, no force-push. All file edits respect LF line endings, no trailing whitespace, no whitespace-only churn.
