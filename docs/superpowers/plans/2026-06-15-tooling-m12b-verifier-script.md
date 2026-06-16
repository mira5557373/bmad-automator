# M12b — Retraction Format Verifier Script Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Land the `scripts/verify_retraction_format.py` contributor gate plus its unittest, document its invocation in `CONTRIBUTING.md`, and prove the new gate does not regress the M11 vocabulary gates — covering REQ-10, REQ-11, and REQ-12 from `docs/superpowers/specs/2026-06-14-m12-retraction-convention.md`.

**Architecture:** A single ~60-line pure-stdlib Python script (`scripts/verify_retraction_format.py`) walks every `*.md` file under `docs/changelog/`, scans for `### Retractions` sub-sections (skipping fenced code blocks so the worked-example fences inside any changelog entry are not mistaken for live retractions), and validates each bullet against the REQ-02 regex. A `main(changelog_dir: Path | None = None) -> int` entry point returns `0` on a clean tree and `1` on any malformed bullet, so the same function powers both `python scripts/verify_retraction_format.py` from CLI and the test-suite assertions. One unittest module (`tests/test_retraction_format.py`) exercises the validator against fixture trees in a `tempfile.TemporaryDirectory` plus one live integration check against the real `docs/changelog/` tree. `CONTRIBUTING.md` gains exactly one new bullet under "Before Opening A PR" with the exact invocation `python scripts/verify_retraction_format.py`. The M11 gate's frozen line signature is extended by one entry (the new `docs/changelog/260616.md` milestone entry) and Gate 6's diff pathspec gains `:!docs/changelog/260616.md` so the wholly-new entry is not flagged as historical-prose mutation — mirroring the carve-out M12a made for `260615.md`.

**Tech Stack:** Python 3.11+ stdlib only (`re`, `pathlib`, `sys`), `unittest` (no pytest), `ruff` for lint and format checks, `bash` only for invoking the M11 portable gate. No new runtime dependencies. The verifier must not import `filelock`, `psutil`, or anything from `story_automator.*`.

---

## Spec mapping

| Req | Where landed | How verified |
|-----|--------------|--------------|
| REQ-10 | `scripts/verify_retraction_format.py` — pure-stdlib validator that exits non-zero on any malformed `### Retractions` bullet across `docs/changelog/*.md` | Task 4 unittest GREEN; Task 6 ruff clean; Task 14 final invocation exits 0 |
| REQ-11 | `CONTRIBUTING.md` — new bullet under "Before Opening A PR" with the exact string `python scripts/verify_retraction_format.py` | Task 8 grep assertion; Task 14 final visual check |
| REQ-12 | M11 vocabulary gates still PASS after the change; Gate 5 signature extended for the new `260616.md` entry; Gate 6 pathspec extended with `:!docs/changelog/260616.md` to exclude the wholly-new milestone entry from the historical-prose-immutability check | Task 10 `bash scripts/m11-vocabulary-gates.sh` exits 0 |

**Out of scope (deferred to a future sub-milestone, NOT M12b):** REQ-09 (a worked retraction landed in a real historical entry with reciprocal `Retracts:` line). This plan must NOT modify any file matching `docs/changelog/26{04,05}*.md` and must NOT add a `### Retractions` sub-section to any existing changelog entry. The verifier's correctness is proved by tempfile fixtures plus an integration check that the (still-zero-retraction) live tree passes — REQ-09 will land the first real retraction in a later milestone and the same verifier will validate it then.

---

### Task 1: Confirm baseline state is clean

**Files:** (read-only checks)

- [ ] **Step 1: Verify the M12 spec is present**

Run:
```sh
test -f docs/superpowers/specs/2026-06-14-m12-retraction-convention.md && echo "spec present"
```
Expected: `spec present`. If missing, stop — the plan cannot be executed without the spec.

- [ ] **Step 2: Verify the M12a foundation is committed**

Run:
```sh
grep -c '^## Retractions$' CONTRIBUTING.md
test -f docs/changelog/260615.md && echo "M12a present"
```
Expected: first command prints `1` (the `## Retractions` section landed by M12a); second prints `M12a present`. If either fails, stop — M12b cannot proceed before M12a is merged.

- [ ] **Step 3: Verify the M11 vocabulary gate exits zero on the starting tree**

Run:
```sh
bash scripts/m11-vocabulary-gates.sh
```
Expected: every line begins with `PASS:`, exit code 0. If any line begins with `FAIL:`, stop and report — the branch is not in a clean state.

- [ ] **Step 4: Verify the M12b artifacts do NOT yet exist**

Run:
```sh
test -f scripts/verify_retraction_format.py && echo "VIOLATION: script already present" || echo "REQ-10 script absent — expected"
test -f tests/test_retraction_format.py && echo "VIOLATION: test already present" || echo "REQ-10 test absent — expected"
test -f docs/changelog/260616.md && echo "VIOLATION: 260616 entry already present" || echo "M12b changelog entry absent — expected"
```
Expected: three lines, each saying "absent — expected". If any reports `VIOLATION`, stop — the milestone is partially landed.

- [ ] **Step 5: Verify the working tree is clean**

Run:
```sh
git status --porcelain
```
Expected: empty output. Only the plan file at `docs/superpowers/plans/2026-06-15-tooling-m12b-verifier-script.md` may appear (already committed by the Phase A step). If anything else appears, stop and resolve.

- [ ] **Step 6: No commit at this step**

Baseline checks only — proceed to Task 2.

---

### Task 2: Write the failing unittest (REQ-10 RED)

**Files:**
- Create: `tests/test_retraction_format.py`

The test fixture writes minimal markdown bodies into a `tempfile.TemporaryDirectory()` and invokes the verifier's `main(changelog_dir)` function with that directory. The script does not yet exist, so importing it must fail loudly — that is the RED step. A separate test invokes `main()` (no argument) against the real `docs/changelog/` tree, proving the live tree stays clean after the script lands.

- [ ] **Step 1: Create `tests/test_retraction_format.py` with this exact content**

```python
"""Unit tests for scripts/verify_retraction_format.py (REQ-10)."""

from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPO_ROOT / "scripts" / "verify_retraction_format.py"


def _load_module():
    spec = importlib.util.spec_from_file_location(
        "verify_retraction_format", SCRIPT_PATH
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class RetractionFormatTests(unittest.TestCase):
    def setUp(self) -> None:
        self.module = _load_module()
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _write(self, name: str, body: str) -> None:
        (self.dir / name).write_text(body, encoding="utf-8")

    def test_empty_directory_returns_zero(self) -> None:
        self.assertEqual(self.module.main(self.dir), 0)

    def test_no_retractions_section_returns_zero(self) -> None:
        self._write(
            "260101.md",
            "## 260101 - [FULL] x\n\n### Summary\nstuff\n",
        )
        self.assertEqual(self.module.main(self.dir), 0)

    def test_valid_retraction_bullet_returns_zero(self) -> None:
        body = (
            "## 260101 - [FULL] x\n\n"
            "### Retractions\n"
            "- [2026-06-15] Retracted by [260612#tmux-fix]"
            "(./260612.md#tmux-fix): regressed in CI.\n"
        )
        self._write("260101.md", body)
        self.assertEqual(self.module.main(self.dir), 0)

    def test_multiple_valid_bullets_return_zero(self) -> None:
        body = (
            "## 260101 - [FULL] x\n\n"
            "### Retractions\n"
            "- [2026-06-15] Retracted by [260612#a]"
            "(./260612.md#a): first.\n"
            "- [2026-08-01] Retracted by [260801#b]"
            "(./260801.md#b): second.\n"
        )
        self._write("260101.md", body)
        self.assertEqual(self.module.main(self.dir), 0)

    def test_malformed_date_format_returns_one(self) -> None:
        body = (
            "## 260101 - [FULL] x\n\n"
            "### Retractions\n"
            "- [26-06-15] Retracted by [260612#tmux-fix]"
            "(./260612.md#tmux-fix): bad date.\n"
        )
        self._write("260101.md", body)
        self.assertEqual(self.module.main(self.dir), 1)

    def test_anchor_text_url_mismatch_returns_one(self) -> None:
        body = (
            "## 260101 - [FULL] x\n\n"
            "### Retractions\n"
            "- [2026-06-15] Retracted by [260612#alpha]"
            "(./260612.md#beta): anchor mismatch.\n"
        )
        self._write("260101.md", body)
        self.assertEqual(self.module.main(self.dir), 1)

    def test_yymmdd_ref_file_mismatch_returns_one(self) -> None:
        body = (
            "## 260101 - [FULL] x\n\n"
            "### Retractions\n"
            "- [2026-06-15] Retracted by [260612#a]"
            "(./260613.md#a): file mismatch.\n"
        )
        self._write("260101.md", body)
        self.assertEqual(self.module.main(self.dir), 1)

    def test_missing_reason_returns_one(self) -> None:
        body = (
            "## 260101 - [FULL] x\n\n"
            "### Retractions\n"
            "- [2026-06-15] Retracted by [260612#a]"
            "(./260612.md#a):\n"
        )
        self._write("260101.md", body)
        self.assertEqual(self.module.main(self.dir), 1)

    def test_fenced_code_block_is_skipped(self) -> None:
        body = (
            "## 260101 - [FULL] x\n\n"
            "### Worked example\n\n"
            "```markdown\n"
            "### Retractions\n"
            "- not-a-real-bullet\n"
            "```\n"
        )
        self._write("260101.md", body)
        self.assertEqual(self.module.main(self.dir), 0)

    def test_tilde_fenced_code_block_is_skipped(self) -> None:
        body = (
            "## 260101 - [FULL] x\n\n"
            "### Worked example\n\n"
            "~~~markdown\n"
            "### Retractions\n"
            "- garbage\n"
            "~~~\n"
        )
        self._write("260101.md", body)
        self.assertEqual(self.module.main(self.dir), 0)

    def test_block_terminates_at_next_heading(self) -> None:
        body = (
            "## 260101 - [FULL] x\n\n"
            "### Retractions\n"
            "- [2026-06-15] Retracted by [260612#a]"
            "(./260612.md#a): ok.\n\n"
            "### Notes\n"
            "- this bullet is outside the retractions block\n"
        )
        self._write("260101.md", body)
        self.assertEqual(self.module.main(self.dir), 0)

    def test_crlf_line_endings_are_tolerated(self) -> None:
        # NFR: correct under Windows CRLF, Unix LF, macOS LF without conversion.
        body = (
            "## 260101 - [FULL] x\r\n"
            "\r\n"
            "### Retractions\r\n"
            "- [2026-06-15] Retracted by [260612#tmux-fix]"
            "(./260612.md#tmux-fix): regressed in CI.\r\n"
        )
        (self.dir / "260101.md").write_bytes(body.encode("utf-8"))
        self.assertEqual(self.module.main(self.dir), 0)

    def test_m12a_worked_example_bullet_validates(self) -> None:
        # The literal bullet from the M12a worked example in CONTRIBUTING.md.
        body = (
            "## 260501 - [FULL] tmux runtime keepalive\n\n"
            "### Retractions\n"
            "- [2026-06-15] Retracted by "
            "[260612#tmux-keepalive-regression-fix]"
            "(./260612.md#tmux-keepalive-regression-fix): "
            "keepalive ping interval regressed in CI; "
            "superseded by the fix entry.\n"
        )
        self._write("260501.md", body)
        self.assertEqual(self.module.main(self.dir), 0)

    def test_live_changelog_tree_is_clean(self) -> None:
        # Integration: the real docs/changelog/ tree must be REQ-10 clean.
        self.assertEqual(self.module.main(), 0)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the test to confirm it fails because the script does not exist**

Run:
```sh
PYTHONPATH=skills/bmad-story-automator/src python3 -m unittest tests.test_retraction_format -v
```
Expected: every test ERRORS (not FAILs) with `FileNotFoundError` or `AttributeError` because `scripts/verify_retraction_format.py` does not yet exist and `spec_from_file_location` returns a spec whose loader fails to find the file. Confirm the suite exits non-zero. If the suite passes, stop — the test is not actually testing the missing script.

- [ ] **Step 3: No commit yet — the script lands in Task 3 and the commit happens in Task 13**

---

### Task 3: Implement the verifier script (REQ-10 GREEN)

**Files:**
- Create: `scripts/verify_retraction_format.py`

The script must be pure-stdlib, under 80 LOC, ruff-clean, and complete in under one second on the full live changelog set. The validator returns a list of error strings rather than raising, so `main()` can sort and print them deterministically.

- [ ] **Step 1: Create `scripts/verify_retraction_format.py` with this exact content**

```python
"""Validate REQ-02 retraction bullet format across docs/changelog/*.md.

Exits 0 if every ### Retractions bullet matches the REQ-02 syntax; exits 1
on any malformed bullet, printing one error line per problem to stderr.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
CHANGELOG_DIR = REPO_ROOT / "docs" / "changelog"

# REQ-02: - [YYYY-MM-DD] Retracted by [YYMMDD#anchor](./YYMMDD.md#anchor): <reason>
BULLET_RE = re.compile(
    r"^- \[(?P<date>\d{4}-\d{2}-\d{2})\] "
    r"Retracted by \[(?P<ref>\d{6})#(?P<anchor>[a-z0-9_-]+)\]"
    r"\(\./(?P<file>\d{6})\.md#(?P<anchor2>[a-z0-9_-]+)\): "
    r"(?P<reason>\S.*)$"
)

RETRACTIONS_HEADING_RE = re.compile(r"^### Retractions\s*$")
ANY_HEADING_RE = re.compile(r"^#{1,6}\s")
FENCE_RE = re.compile(r"^(```|~~~)")


def find_retraction_bullets(content: str) -> list[tuple[int, str]]:
    """Return [(line_no, line)] for each bullet inside ### Retractions blocks.

    Skips fenced code blocks (``` or ~~~). line_no is 1-based. A block ends
    at the next markdown heading at any level.
    """
    bullets: list[tuple[int, str]] = []
    in_fence = False
    in_block = False
    for i, line in enumerate(content.splitlines(), start=1):
        if FENCE_RE.match(line):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        if RETRACTIONS_HEADING_RE.match(line):
            in_block = True
            continue
        if in_block and ANY_HEADING_RE.match(line):
            in_block = False
            continue
        if in_block and line.startswith("- "):
            bullets.append((i, line))
    return bullets


def validate_file(path: Path) -> list[str]:
    errors: list[str] = []
    content = path.read_text(encoding="utf-8")
    for lineno, line in find_retraction_bullets(content):
        match = BULLET_RE.match(line)
        if match is None:
            errors.append(
                f"{path}:{lineno}: malformed retraction bullet: {line!r}"
            )
            continue
        if match.group("ref") != match.group("file"):
            errors.append(
                f"{path}:{lineno}: YYMMDD ref/file mismatch "
                f"({match.group('ref')} vs {match.group('file')})"
            )
        if match.group("anchor") != match.group("anchor2"):
            errors.append(
                f"{path}:{lineno}: anchor text/url mismatch "
                f"({match.group('anchor')!r} vs {match.group('anchor2')!r})"
            )
    return errors


def main(changelog_dir: Path | None = None) -> int:
    target = changelog_dir if changelog_dir is not None else CHANGELOG_DIR
    all_errors: list[str] = []
    for path in sorted(target.glob("*.md")):
        all_errors.extend(validate_file(path))
    for err in all_errors:
        print(err, file=sys.stderr)
    return 1 if all_errors else 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: Confirm the script line count is under 80**

Run:
```sh
wc -l scripts/verify_retraction_format.py
```
Expected: a number strictly less than 80 (empirically ~72).

- [ ] **Step 3: Confirm only stdlib imports**

Run:
```sh
grep -E '^(import|from)' scripts/verify_retraction_format.py
```
Expected: only `re`, `sys`, `pathlib`, and the `__future__` annotation line — no `filelock`, no `psutil`, no `story_automator.*`.

- [ ] **Step 4: No commit yet**

---

### Task 4: Run the unittest suite — confirm GREEN

**Files:** (read-only)

- [ ] **Step 1: Run the new unittest module**

Run:
```sh
PYTHONPATH=skills/bmad-story-automator/src python3 -m unittest tests.test_retraction_format -v
```
Expected: every test PASSES, exit code 0. Output includes `Ran 14 tests` and ends with `OK`.

- [ ] **Step 2: Run the full unittest suite to confirm no cross-test regressions**

Run:
```sh
PYTHONPATH=skills/bmad-story-automator/src python3 -m unittest discover -s tests
```
Expected: the full suite (13 prior test files + the new one = 14) passes. If any prior test fails, stop and investigate — M12b must not regress anything under `tests/`.

- [ ] **Step 3: No commit yet**

---

### Task 5: Confirm the script completes in under one second on the live tree (NFR)

**Files:** (read-only)

- [ ] **Step 1: Time a cold invocation against the real `docs/changelog/` tree**

Run:
```sh
time python3 scripts/verify_retraction_format.py
echo "exit=$?"
```
Expected: real-time output well under `0m01.000s`; `exit=0`. If the run takes longer than one second the script violates the NFR "complete in under one second on the full historical changelog set" — investigate before continuing.

- [ ] **Step 2: No commit yet**

---

### Task 6: Lint and format — `ruff check` and `ruff format --check`

**Files:** (read-only checks against the two new files)

- [ ] **Step 1: Run `ruff check` against both files**

Run:
```sh
python3 -m ruff check scripts/verify_retraction_format.py tests/test_retraction_format.py
```
Expected: `All checks passed!`, exit 0. If ruff reports any violation, fix the source until it is clean — do NOT add a `# noqa` to silence a real issue.

- [ ] **Step 2: Run `ruff format --check` against both files**

Run:
```sh
python3 -m ruff format --check scripts/verify_retraction_format.py tests/test_retraction_format.py
```
Expected: `2 files already formatted`, exit 0. If ruff reports `would reformat`, run `python3 -m ruff format scripts/verify_retraction_format.py tests/test_retraction_format.py` to apply the formatting, then re-run the check.

- [ ] **Step 3: Re-run the unittest module after any ruff-format pass**

Run:
```sh
PYTHONPATH=skills/bmad-story-automator/src python3 -m unittest tests.test_retraction_format -v
```
Expected: still GREEN. If formatting broke a test (it shouldn't, since both files are mechanical), restore the offending line by hand.

- [ ] **Step 4: No commit yet**

---

### Task 7: Confirm no four-letter placeholder leaks (NFR)

**Files:** (read-only check)

- [ ] **Step 1: Grep for unresolved placeholder tokens across the three target files**

Run:
```sh
grep -nE '\b(TODO|TBD|FIXME|XXXX)\b' CONTRIBUTING.md scripts/verify_retraction_format.py tests/test_retraction_format.py || echo "no placeholders"
```
Expected: `no placeholders`. Note that `YYYY` and `YYMMDD` are legitimate placeholder tokens inside the REQ-02 syntax fragment — the grep above only flags the four blocked tokens.

- [ ] **Step 2: No commit yet**

---

### Task 8: Document the gate invocation in `CONTRIBUTING.md` (REQ-11)

**Files:**
- Modify: `CONTRIBUTING.md` — append exactly one bullet under the existing `## Before Opening A PR` `- run:` block, plus one short prose sentence immediately after that section's `- run:` list to record the expected exit-zero contract

The bullet must contain the exact string `python scripts/verify_retraction_format.py` so REQ-11 ("documented contributor gate in `CONTRIBUTING.md` with the exact invocation … and an expected exit-zero behavior on a clean tree") is byte-satisfied; the trailing prose sentence makes the exit-zero half explicit. The existing `## Retractions` section landed by M12a stays byte-for-byte unchanged.

- [ ] **Step 1: Confirm the insertion anchor still matches the expected current contents**

Run:
```sh
grep -nE '^  - `PYTHONPATH=skills/bmad-story-automator/src python3 -m story_automator --help`$' CONTRIBUTING.md
```
Expected: exactly one match. Record the line number — the new bullet is inserted on the line immediately after this match.

- [ ] **Step 2: Append the new bullet directly after the `--help` bullet**

Insert this single line immediately below the matched `--help` bullet, preserving the two-space indentation used by the surrounding bullets:

```text
  - `python scripts/verify_retraction_format.py`
```

The resulting `- run:` block must read:

```text
- run:
  - `npm run pack:dry-run`
  - `npm run test:smoke`
  - `PYTHONPATH=skills/bmad-story-automator/src python3 -m story_automator --help`
  - `python scripts/verify_retraction_format.py`
```

- [ ] **Step 3: Append one prose sentence after the `- run:` list recording the exit-zero contract**

Insert the following standalone paragraph immediately AFTER the last bullet of the `- run:` list and BEFORE the next `##` heading, separated by one blank line above and one blank line below:

```text
The `python scripts/verify_retraction_format.py` gate is expected to exit 0 on a clean tree; a non-zero exit indicates a malformed `### Retractions` bullet under `docs/changelog/` that must be fixed before opening the PR.
```

This satisfies the second half of REQ-11 ("an expected exit-zero behavior on a clean tree") in explicit prose without altering the existing bullet style.

- [ ] **Step 4: Confirm the exact REQ-11 invocation is present byte-for-byte**

Run:
```sh
grep -cF '`python scripts/verify_retraction_format.py`' CONTRIBUTING.md
```
Expected: `2` — one occurrence in the `- run:` bullet, one in the prose sentence added in Step 3.

- [ ] **Step 5: Confirm the explicit exit-zero clause is present**

Run:
```sh
grep -cF 'exit 0 on a clean tree' CONTRIBUTING.md
```
Expected: `1`.

- [ ] **Step 6: Confirm the M12a `## Retractions` section is byte-for-byte unchanged**

Run:
```sh
git diff -- CONTRIBUTING.md | grep -E '^[+-]' | grep -E '^[+-]## Retractions$|^[+-]### Worked example$' || echo "M12a section unchanged"
```
Expected: `M12a section unchanged`. The diff must NOT delete or modify any line inside the M12a `## Retractions` section — only the new `- run:` bullet and the new exit-zero prose sentence are added.

- [ ] **Step 7: Confirm no whitespace hygiene regressions on the doc edit**

Run:
```sh
git diff --check -- CONTRIBUTING.md
```
Expected: empty output, exit 0.

- [ ] **Step 8: Confirm no CRLF was introduced**

Run:
```sh
LC_ALL=C grep -l "$(printf '\r')" CONTRIBUTING.md && echo "FAIL: CRLF detected" || echo "LF-only — ok"
```
Expected: `LF-only — ok`.

- [ ] **Step 9: No commit yet**

---

### Task 9: Extend the M11 portable gate for the new changelog entry (REQ-12)

**Files:**
- Modify: `scripts/m11-vocabulary-gates.sh` — two small surgical edits, both directly modelled on the M12a precedent already in the file

Gate 5's frozen line signature must learn the new `docs/changelog/260616.md` entry (REQ-11 ordering-preservation does not consider a new file a regression, but the signature must enumerate every file with dated headings, so we must extend it explicitly). Gate 6's diff pathspec must exclude `docs/changelog/260616.md` for the same reason `260615.md` was excluded by M12a — the wholly-new milestone entry is not a modification of an existing historical entry, and REQ-10 only constrains historical entries' prose.

- [ ] **Step 1: Extend Gate 5's `EXPECTED` here-string with one new line for `260616.md`**

Edit `scripts/m11-vocabulary-gates.sh`. Find the block:

```sh
docs/changelog/260519.md:3
docs/changelog/260615.md:3"
```

Replace it byte-for-byte with:

```sh
docs/changelog/260519.md:3
docs/changelog/260615.md:3
docs/changelog/260616.md:3"
```

The trailing `"` must remain on the new last line. No other line in `EXPECTED` may move.

- [ ] **Step 2: Extend Gate 6's exclude pathspec**

In the same file, find the line:

```sh
  NON_HEADING=$(git diff -U0 "$BASE"...HEAD -- 'docs/changelog/*.md' ':!docs/changelog/AUDIT.md' ':!docs/changelog/260615.md' \
```

Replace it byte-for-byte with:

```sh
  NON_HEADING=$(git diff -U0 "$BASE"...HEAD -- 'docs/changelog/*.md' ':!docs/changelog/AUDIT.md' ':!docs/changelog/260615.md' ':!docs/changelog/260616.md' \
```

No other line in Gate 6 may move.

- [ ] **Step 3: Confirm no whitespace hygiene regressions on the gate edit**

Run:
```sh
git diff --check -- scripts/m11-vocabulary-gates.sh
```
Expected: empty output, exit 0. If git reports CRLF or trailing whitespace, fix the offending line and re-check.

- [ ] **Step 4: No commit yet — the gate self-test happens in Task 10 after the new changelog file is authored**

---

### Task 10: Author the `docs/changelog/260616.md` milestone entry

**Files:**
- Create: `docs/changelog/260616.md`

The new entry carries exactly one M11 scope tag. M12b lands implementation + tests + ruff cleanliness + gate documentation + non-regression of the M11 gate, so it is `[FULL]` per the M11 vocabulary definition ("a change shipped with spec, implementation, tests, and verification all complete and passing every quality gate at merge time").

- [ ] **Step 1: Create `docs/changelog/260616.md` with this exact content**

```markdown
# Changelog - 260616

## 260616 - [FULL] M12b retraction format verifier script

### Summary
Lands `scripts/verify_retraction_format.py`, a pure-stdlib Python script that validates every `### Retractions` bullet across `docs/changelog/*.md` against the REQ-02 regex from the M12 spec. Implements REQ-10, REQ-11, and REQ-12 of `docs/superpowers/specs/2026-06-14-m12-retraction-convention.md`. REQ-09 (a worked retraction landed in a real historical entry) remains deferred to a future sub-milestone — this entry's `[FULL]` tag covers REQ-10/11/12 only, not the full M12 spec.

### Added
- `scripts/verify_retraction_format.py` — pure-stdlib validator, under 80 LOC, completes in under one second on the full live changelog set. Exits 0 on a clean tree, 1 on any malformed bullet, printing one error line per problem to stderr.
- `tests/test_retraction_format.py` — unittest module covering the REQ-02 regex (valid bullet, multiple bullets, malformed date, anchor mismatch, YYMMDD-vs-file mismatch, missing reason), fenced-code-block skipping for both `` ``` `` and `~~~` fences, block-terminates-at-next-heading semantics, CRLF line-ending tolerance (per the NFR that the convention "must remain correct under all three line-ending policies"), the literal M12a worked-example bullet, and a live integration check that the real `docs/changelog/` tree exits zero.

### Changed
- `CONTRIBUTING.md` — appended one bullet `` `python scripts/verify_retraction_format.py` `` to the existing `- run:` list under `## Before Opening A PR` plus one short prose sentence recording the gate's expected exit-zero behavior on a clean tree, jointly satisfying REQ-11 (both the exact invocation and the documented exit-zero contract). The M12a `## Retractions` section is byte-for-byte unchanged.
- `scripts/m11-vocabulary-gates.sh` Gate 5 (REQ-11 ordering-preservation) — the frozen line-number signature is extended by one line so the new `docs/changelog/260616.md` entry is recognized. No existing entry's line numbers move.
- `scripts/m11-vocabulary-gates.sh` Gate 6 (REQ-10 prose-immutability) — the diff-vs-base pathspec is extended with `:!docs/changelog/260616.md` so the wholly-new M12b milestone entry is excluded from the historical-prose mutation check. The exclusion mirrors the pre-existing carve-outs for `AUDIT.md` and `260615.md` and rests on the same rationale: REQ-10 constrains historical entries only.

### Files
- `scripts/verify_retraction_format.py` — new verifier.
- `tests/test_retraction_format.py` — new unittest module.
- `CONTRIBUTING.md` — one new bullet under `## Before Opening A PR`.
- `scripts/m11-vocabulary-gates.sh` — one-line Gate 5 signature extension; one-token Gate 6 pathspec extension.
- `docs/changelog/260616.md` — this entry.
- `docs/superpowers/plans/2026-06-15-tooling-m12b-verifier-script.md` — implementation plan.

### QA Notes
- `PYTHONPATH=skills/bmad-story-automator/src python3 -m unittest tests.test_retraction_format -v` — every test PASS, exit 0.
- `PYTHONPATH=skills/bmad-story-automator/src python3 -m unittest discover -s tests` — full suite PASS, no prior-test regression.
- `python3 scripts/verify_retraction_format.py` — exits 0 on the live tree.
- `python3 -m ruff check scripts/verify_retraction_format.py tests/test_retraction_format.py` — `All checks passed!`.
- `python3 -m ruff format --check scripts/verify_retraction_format.py tests/test_retraction_format.py` — both files already formatted.
- `bash scripts/m11-vocabulary-gates.sh` — every gate PASS, exit 0 (REQ-12 non-regression).
- `git diff --check` — no whitespace hygiene violations on any changed file.
- Total M12 line delta vs `bma-d/m11-changelog-vocabulary` remains under the 280-line NFR cap.
```

- [ ] **Step 2: Verify the entry carries exactly one M11 tag on its dated heading**

Run:
```sh
grep -cE '^## 260616 - \[(FULL|LITE|SKELETON|DEFERRED)\] ' docs/changelog/260616.md
```
Expected: `1`. If not 1, the heading is malformed.

- [ ] **Step 3: No commit yet**

---

### Task 11: Verify the M11 portable gate still passes (REQ-12)

**Files:** (read-only checks)

- [ ] **Step 1: Run the full M11 gate**

Run:
```sh
bash scripts/m11-vocabulary-gates.sh
```
Expected: every line begins with `PASS:` (or one `SKIP:` line for Gate 6 if the base ref is unreachable in a shallow checkout), exit code 0. If any line begins with `FAIL:`, stop and investigate:
- `REQ-11 ordering-preservation drift detected` → Gate 5's signature was extended incorrectly in Task 9 step 1. Re-check that exactly one new line `docs/changelog/260616.md:3` was added and the trailing `"` is on that new last line.
- `REQ-10 prose-immutability: non-heading changes under docs/changelog/` → Gate 6's pathspec was not extended in Task 9 step 2, so the new `260616.md` entry's body lines are being flagged as historical mutation. Re-check the pathspec edit.
- `Whitespace hygiene: git diff --check reported violations` → some file has trailing whitespace or CRLF. Fix with `git diff --check` and re-run.
- `Line-ending portability: CRLF detected in:` → the new file was saved CRLF. Re-save LF-only.

- [ ] **Step 2: Re-run the retraction verifier to confirm the live tree is still clean**

Run:
```sh
python3 scripts/verify_retraction_format.py
echo "exit=$?"
```
Expected: no stderr output; `exit=0`. The new `260616.md` entry contains no `### Retractions` block, so the verifier finds zero bullets and exits clean.

- [ ] **Step 3: No commit yet**

---

### Task 12: Verify the total M12 line delta stays under the NFR cap (NFR 280)

**Files:** (read-only check)

- [ ] **Step 1: Confirm the total added-line count across the M12 diff is under 280**

Run:
```sh
BASE=origin/main
git rev-parse --verify --quiet "$BASE" >/dev/null || BASE=main
ADDED=$(git diff "$BASE"...HEAD | grep -cE '^\+[^+]')
echo "added=$ADDED"
[ "$ADDED" -lt 280 ] || echo "FAIL: NFR line-delta breached ($ADDED >= 280)"
```
Expected: a number strictly less than 280 and no `FAIL:` line. If `FAIL:` appears, trim the changelog QA Notes or condense the implementation prose — do NOT silently inline `# noqa` or strip required REQ wording.

- [ ] **Step 2: No commit yet**

---

### Task 13: Stage exactly the intended files and commit

**Files:**
- Commit: `scripts/verify_retraction_format.py`, `tests/test_retraction_format.py`, `CONTRIBUTING.md`, `scripts/m11-vocabulary-gates.sh`, `docs/changelog/260616.md`

NOTE: the plan file `docs/superpowers/plans/2026-06-15-tooling-m12b-verifier-script.md` was committed during Phase A and MUST NOT be re-staged in this implementation commit. The same applies to `.claude/.gap-report.json` and any scratch files.

- [ ] **Step 1: Stage exactly the five intended files**

Run:
```sh
git add scripts/verify_retraction_format.py tests/test_retraction_format.py CONTRIBUTING.md scripts/m11-vocabulary-gates.sh docs/changelog/260616.md
git status --porcelain
```
Expected: exactly five lines:
- `A  scripts/verify_retraction_format.py`
- `A  tests/test_retraction_format.py`
- ` M CONTRIBUTING.md`
- ` M scripts/m11-vocabulary-gates.sh`
- `A  docs/changelog/260616.md`

No `??` lines and no other staged entries. If `.claude/.gap-report.json`, the plan file, or any other path appears, do NOT stage it.

- [ ] **Step 2: Confirm no Python sources under `skills/` were touched (docs-only milestone discipline)**

Run:
```sh
git diff --cached --name-only | grep -E '^(skills/|bin/|install\.sh)' || echo "clean"
```
Expected: `clean`. If any line matches, unstage with `git restore --staged <path>` — M12b does NOT touch the runtime package.

- [ ] **Step 3: Confirm telemetry types are untouched (M01 hard guardrail)**

Run:
```sh
git diff --cached --name-only | grep -F 'telemetry_events.py' || echo "telemetry_events.py untouched"
```
Expected: `telemetry_events.py untouched`. Any match is a guardrail violation — unstage immediately.

- [ ] **Step 4: Confirm no historical changelog entry under `docs/changelog/26{04,05}*.md` was touched (REQ-09 stays deferred)**

Run:
```sh
git diff --cached --name-only -- docs/changelog/ | grep -E '^docs/changelog/26(04|05)' && echo "VIOLATION: historical changelog touched" || echo "REQ-09 still deferred"
```
Expected: `REQ-09 still deferred`. If `VIOLATION` appears, unstage the offending file.

- [ ] **Step 5: Create the commit**

Run the commit with a Conventional Commits subject and the required `Generated-By:` trailer. Replace `<model-name>` with the actual model identifier driving the session (for example `claude-opus-4-7`):

```sh
git commit -m "$(cat <<'EOF'
feat(m12b): add retraction format verifier script and gate doc

Adds scripts/verify_retraction_format.py, a pure-stdlib Python validator
under 80 LOC that exits non-zero on any malformed `### Retractions` bullet
across `docs/changelog/*.md`. Implements REQ-10 of the M12 spec.

Documents the gate invocation in CONTRIBUTING.md under "Before Opening A PR"
with the exact string `python scripts/verify_retraction_format.py` (REQ-11).

Extends the M11 portable gate (`scripts/m11-vocabulary-gates.sh`) by one
line in Gate 5's frozen signature and one token in Gate 6's pathspec so
the new `docs/changelog/260616.md` milestone entry is recognized without
disturbing the historical-prose-immutability contract (REQ-12 non-regression).

REQ-09 (worked retraction landed in a real historical entry) remains
deferred to a future sub-milestone.
EOF
)" --trailer "Generated-By: claude-opus-4-7"
```

Expected: the commit succeeds; `git log -1 --format=%B` shows the `Generated-By:` trailer on its own line at the bottom; the commit subject obeys Conventional Commits.

- [ ] **Step 6: Final verification on the committed state**

Run:
```sh
bash scripts/m11-vocabulary-gates.sh \
  && python3 scripts/verify_retraction_format.py \
  && PYTHONPATH=skills/bmad-story-automator/src python3 -m unittest discover -s tests \
  && git status --porcelain
```
Expected: every M11 gate PASS, then the verifier exits 0 silently, then the unittest suite ends with `OK`, then an empty `git status --porcelain` (clean tree).

---

### Task 14: Post-commit cross-check against the spec

**Files:** (read-only checks)

- [ ] **Step 1: Re-read the spec sections covered by this sub-milestone**

Open `docs/superpowers/specs/2026-06-14-m12-retraction-convention.md` and re-read REQ-10, REQ-11, REQ-12. For each, point to the exact file and line in the committed tree that satisfies it:
- REQ-10 → `scripts/verify_retraction_format.py` (the whole file).
- REQ-11 → the new bullet in `CONTRIBUTING.md` under `## Before Opening A PR`.
- REQ-12 → `bash scripts/m11-vocabulary-gates.sh` exits 0 on HEAD, demonstrated in Task 13 step 6.

- [ ] **Step 2: Confirm REQ-09 remains DEFERRED**

Run:
```sh
git log -1 --name-only | grep -E '^docs/changelog/26(04|05)[0-9]{2}\.md$' && echo "VIOLATION: REQ-09 leaked into M12b" || echo "REQ-09 correctly deferred"
git diff HEAD~1 HEAD -- 'docs/changelog/26[0-1]*.md' 'docs/changelog/26[2-5]*.md' \
  | grep -E '^\+### Retractions$' \
  && echo "VIOLATION: a real retraction bullet leaked into M12b" \
  || echo "REQ-09 sub-section absent — expected"
```
Expected: both lines end in `correctly deferred` / `absent — expected`.

- [ ] **Step 3: Confirm the M12b commit is on the expected branch**

Run:
```sh
git rev-parse --abbrev-ref HEAD
```
Expected: `bma-d/m12-retraction-convention` (the worktree branch name).

- [ ] **Step 4: Confirm the verifier script line count NFR**

Run:
```sh
wc -l scripts/verify_retraction_format.py
```
Expected: a number strictly less than 80.

- [ ] **Step 5: Confirm the cumulative M12 line delta NFR**

Run:
```sh
BASE=origin/main
git rev-parse --verify --quiet "$BASE" >/dev/null || BASE=main
ADDED=$(git diff "$BASE"...HEAD | grep -cE '^\+[^+]')
echo "M12 total added lines vs $BASE: $ADDED (cap 279)"
[ "$ADDED" -lt 280 ] || echo "FAIL: NFR line-delta breached"
```
Expected: a number strictly less than 280 and no `FAIL:` line.

- [ ] **Step 6: No commit at this step**

Plan complete. Hand off to a future sub-milestone for REQ-09 (real retraction landing) — the verifier landed here will validate it.

---

## Out-of-band safety reminders for the executing engineer

- This is a **tooling** sub-milestone — it lands one new Python script under `scripts/`, one new test module under `tests/`, and surgical edits to `CONTRIBUTING.md`, `scripts/m11-vocabulary-gates.sh`, plus one new entry under `docs/changelog/`. If you find yourself editing anything under `skills/bmad-story-automator/src/`, you have drifted outside scope.
- Do NOT modify `skills/bmad-story-automator/src/story_automator/core/telemetry_events.py` — that file is owned by M01 and is a hard guardrail.
- Do NOT modify any existing changelog file under `docs/changelog/26{04,05}*.md`. The only changelog touches are the new `260616.md` entry created in Task 10 and (transitively, via the gate signature update) the already-committed `260615.md` from M12a — the latter is read-only here.
- Do NOT modify the M12a `## Retractions` section in `CONTRIBUTING.md`. REQ-11 is satisfied by appending a bullet under the pre-existing `## Before Opening A PR` block, not by editing the M12a prose.
- Markdown line endings must be LF only — Windows git-bash can silently introduce CRLF. If Gate 7 (`Line-ending portability`) of `scripts/m11-vocabulary-gates.sh` fails after your edit, re-save the file with LF endings.
- If `ruff` is not available in the environment, install it transiently with `python3 -m pip install --user ruff` and re-run the lint and format checks — do NOT skip them.
- The `Generated-By:` trailer in Task 13 must name the actual model driving the session; do not hardcode an outdated identifier.
- The verifier script must NOT import anything from `story_automator.*` or pull in `filelock` / `psutil`. It is a pure-stdlib quality gate that must be runnable from a freshly-cloned tree without first installing the runtime package.
