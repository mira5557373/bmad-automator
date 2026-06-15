# M12c — Worked Retraction Example Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Land a real, byte-for-byte-compliant worked retraction example in `docs/changelog/260413.md` that satisfies REQ-09 (which transitively requires REQ-02, REQ-03, REQ-05, REQ-06), keep the M11 vocabulary gate green by widening it to permit retraction additions, and keep the M12b verifier green on the live tree.

**Architecture:** A round-trip retraction is landed inside `docs/changelog/260413.md` between a real defect-fix pair: defect entry `260413-08:39:42 - [FULL] Route create validation through shared verifier` (which added `orchestrator-helper verify-step`) and fix entry `260413-09:14:32 - [FULL] Restore verify-step retry contract` (whose summary literally reads "Restored the shared verifier CLI contract"). The defect entry gains an appended `### Retractions` sub-section with a single REQ-02-shaped bullet; the fix entry gains an appended `### Notes` sub-section carrying a single `Retracts:` reciprocal link line. The M11 vocabulary gate script `scripts/m11-vocabulary-gates.sh` is widened (Gate 6 allows-list, Gate 5 line-number signature refresh) so the legitimate retraction additions do not register as prose modifications. New `unittest` coverage in `tests/test_retraction_format.py` pins the round-trip byte-for-byte and the live-tree integration test continues to assert verifier exit 0.

**Tech Stack:** Python 3.11 stdlib (`re`, `pathlib`, `unittest`), POSIX `sh` for `m11-vocabulary-gates.sh`, Markdown for `docs/changelog/260413.md`, `ruff` for lint/format.

---

## File structure

- **Modify** `docs/changelog/260413.md`
  - append a `### Retractions` block to the defect entry (`## 260413-08:39:42 - [FULL] Route create validation through shared verifier`)
  - append a `### Notes` block to the fix entry (`## 260413-09:14:32 - [FULL] Restore verify-step retry contract`)
- **Modify** `scripts/m11-vocabulary-gates.sh`
  - Gate 5: refresh the frozen line-number signature for `docs/changelog/260413.md` to account for the two appended blocks
  - Gate 6: widen the `NON_HEADING` filter so added lines matching the retraction grammar (`### Retractions`, `### Notes`, the REQ-02 bullet form, and the `Retracts:` form) are not flagged as prose modifications; deletions remain forbidden
- **Modify** `tests/test_retraction_format.py`
  - append a new `RetractionRoundTripTests` test class that pins the round-trip byte-for-byte: the defect entry's appended bullet validates under the REQ-02 regex, the fix entry's `Retracts:` line round-trip-links back, and the original prose of both entries is preserved verbatim
- **Create** `docs/changelog/260617.md`
  - new file containing the M12c milestone changelog entry under the next milestone-incremented date with the closed-vocab `[FULL]` tag. M12a used `260615.md` and M12b used `260616.md`; M12c follows the same one-file-per-milestone pattern to avoid mutating M12a's entry. Gate 5's frozen signature gains one new line; Gate 6's exclude pathspec gains `:!docs/changelog/260617.md` for the same reason `260615.md` and `260616.md` are excluded (a wholly new milestone entry is not a modification of a historical entry).

No new files are created. No Python source under `skills/bmad-story-automator/src/` is touched.

## Worked-example slug derivation (reference for all tasks)

GitHub-flavored Markdown auto-slugs are produced by: (1) lowercase the heading text, (2) strip every character that is not alphanumeric, hyphen, underscore, or whitespace, (3) replace each whitespace character with a single hyphen, (4) preserve any consecutive hyphens produced (no collapsing).

- Defect heading text: `260413-08:39:42 - [FULL] Route create validation through shared verifier`
  - lowercase: `260413-08:39:42 - [full] route create validation through shared verifier`
  - strip `:`, `[`, `]`: `260413-083942 - full route create validation through shared verifier`
  - spaces → `-`: `260413-083942---full-route-create-validation-through-shared-verifier`
  - **defect anchor:** `260413-083942---full-route-create-validation-through-shared-verifier`
- Fix heading text: `260413-09:14:32 - [FULL] Restore verify-step retry contract`
  - lowercase: `260413-09:14:32 - [full] restore verify-step retry contract`
  - strip `:`, `[`, `]`: `260413-091432 - full restore verify-step retry contract`
  - spaces → `-`: `260413-091432---full-restore-verify-step-retry-contract`
  - **fix anchor:** `260413-091432---full-restore-verify-step-retry-contract`

Both anchors are pure `[a-z0-9_-]+` and pass the M12b verifier regex on `scripts/verify_retraction_format.py:12-16`. The reciprocal link from fix→defect uses the defect anchor; the retraction bullet's link from defect→fix uses the fix anchor.

---

## Task 1: Establish a clean pre-change baseline

**Files:**
- Read: `docs/changelog/260413.md`
- Read: `scripts/m11-vocabulary-gates.sh`
- Read: `scripts/verify_retraction_format.py`

- [ ] **Step 1: Confirm REQ-04 nine-month bound**

REQ-04 forbids applying a retraction to an entry that pre-dates the M12 commit by more than nine months. The M12 commit lands on 2026-06-15; nine months before is 2025-09-15. The defect entry is dated 2026-04-13 (`260413`), which is ~2 months before today — well inside the window. Record this as a precondition; no command to run, but the plan must not proceed if the chosen historical date is outside this bound.

- [ ] **Step 2: Confirm the live changelog tree is currently clean under the M12b verifier**

Run: `python scripts/verify_retraction_format.py; echo "exit=$?"`
Expected: `exit=0` and no stderr output. This is the M12b baseline that must stay green throughout M12c.

- [ ] **Step 3: Confirm the M11 vocabulary gates currently pass against `main`**

Run: `BASE=main sh scripts/m11-vocabulary-gates.sh`
Expected: every gate prints `PASS:` and the script exits 0. This is the M11 baseline.

- [ ] **Step 4: Capture the current line-number signature for `docs/changelog/260413.md`**

Run: `grep -nE '^##+ [0-9]{6}' docs/changelog/260413.md | cut -d: -f1 | tr '\n' ',' | sed 's/,$//'`
Expected output: `3,27,51,77,104,129,148,168,195,215,250,277,302,330` — matches `EXPECTED` block in `scripts/m11-vocabulary-gates.sh:51-62` for that file.

- [ ] **Step 5: Confirm the defect and fix entry block boundaries**

Run: `grep -n '^## 260413-' docs/changelog/260413.md`
Expected: line 77 is `## 260413-08:39:42 - [FULL] Route create validation through shared verifier`; line 104 is `## 260413-08:34:25 - [FULL] Harden success verifier review fixes`; line 3 is `## 260413-09:14:32 - [FULL] Restore verify-step retry contract`; line 27 is `## 260413-08:05:51 - [LITE] Wire policy-backed success verifiers`. The defect entry spans lines 77 through the blank line immediately before line 104. The fix entry spans lines 3 through the blank line immediately before line 27. Both entries' last sub-section is `### QA Notes` containing `- `npm run verify``.

No commit at this stage — Task 1 is read-only baselining.

---

## Task 2: Widen Gate 6 of the M11 vocabulary gates to allow retraction additions

**Files:**
- Modify: `scripts/m11-vocabulary-gates.sh:82-103`

REQ-12 requires that the M11 contributor-guide grep gate continue to pass after M12 lands. The current `Gate 6 — REQ-10 prose-immutability` filter (`scripts/m11-vocabulary-gates.sh:90-98`) treats any added or removed non-dated-heading line under `docs/changelog/*.md` as a violation. The legitimate M12c additions (a `### Retractions` sub-section on the defect entry; a `### Notes` sub-section with a `Retracts:` line on the fix entry) would falsely trip the gate. The fix is to extend the existing `grep -vE` exclusion chain with allow-list patterns for the four retraction-related forms, applied ONLY to additions (`^\+`), never deletions (`^-`), so prose immutability remains intact.

- [ ] **Step 1: Write the failing test (manual gate run)**

Run: `BASE=main sh scripts/m11-vocabulary-gates.sh; echo "exit=$?"`
Expected at this stage (Gate 6 not yet widened, no changelog modifications yet): `exit=0` because no diff exists. This step is the "before" snapshot — we will re-run it after the changelog edits in later tasks and confirm Gate 6 still passes thanks to the widening.

To simulate a future positive case: also confirm the gate exit code is what we expect when there IS a retraction diff. Skip this sub-check here — it is covered end-to-end by Task 8.

- [ ] **Step 2: Apply the Gate 6 widening**

Edit `scripts/m11-vocabulary-gates.sh:90-98`. Replace the current `NON_HEADING=$(...)` assignment with the widened chain. The exact replacement is:

Find this block:

```sh
  NON_HEADING=$(git diff -U0 "$BASE"...HEAD -- 'docs/changelog/*.md' ':!docs/changelog/AUDIT.md' ':!docs/changelog/260615.md' ':!docs/changelog/260616.md' \
    | grep -E '^[+-][^+-]' \
    | grep -vE '^[+-]## [0-9]{6}' || true)
  [ -z "$NON_HEADING" ] || fail "REQ-10 prose-immutability: non-heading changes under docs/changelog/:
$NON_HEADING"
  pass "REQ-10 prose-immutability (only dated headings changed vs $BASE)"
```

Replace with:

```sh
  # M12c — Gate 6 allows four retraction-related ADDITIONS (^+ only) so the
  # retraction convention can land its worked example without falsely tripping
  # prose-immutability. Deletions (^-) under docs/changelog/*.md remain
  # forbidden, preserving the original M11 intent.
  NON_HEADING=$(git diff -U0 "$BASE"...HEAD -- 'docs/changelog/*.md' ':!docs/changelog/AUDIT.md' ':!docs/changelog/260615.md' ':!docs/changelog/260616.md' ':!docs/changelog/260617.md' \
    | grep -E '^[+-][^+-]' \
    | grep -vE '^[+-]## [0-9]{6}' \
    | grep -vE '^\+### Retractions[[:space:]]*$' \
    | grep -vE '^\+### Notes[[:space:]]*$' \
    | grep -vE '^\+- \[20[0-9]{2}-[0-9]{2}-[0-9]{2}\] Retracted by \[[0-9]{6}#[a-z0-9_-]+\]\(\./[0-9]{6}\.md#[a-z0-9_-]+\): [^[:space:]].*$' \
    | grep -vE '^\+Retracts: \[[0-9]{6}#[a-z0-9_-]+\]\(\./[0-9]{6}\.md#[a-z0-9_-]+\)[[:space:]]*$' \
    || true)
  [ -z "$NON_HEADING" ] || fail "REQ-10 prose-immutability: non-heading changes under docs/changelog/:
$NON_HEADING"
  pass "REQ-10 prose-immutability (only dated headings + retraction additions changed vs $BASE)"
```

Rationale: the exclude pathspec gains `:!docs/changelog/260617.md` so the M12c milestone entry (wholly new) is treated the same as the M12a/M12b milestone entries. Each of the four new `grep -vE` lines anchors on `^\+` so deletions are never excluded; date format `20[0-9]{2}-...` constrains retraction-bullet dates to the legitimate 21st-century range; YYMMDD ref / anchor patterns match the M12b verifier regex (`scripts/verify_retraction_format.py:12-16`); `[^[:space:]].*$` on the bullet's reason field enforces a non-empty reason exactly as the verifier does; `[[:space:]]*$` on the `Retracts:` line tolerates trailing whitespace defensively without permitting any other content.

- [ ] **Step 3: Re-run the gate against `main` to confirm it still passes with no diff**

Run: `BASE=main sh scripts/m11-vocabulary-gates.sh; echo "exit=$?"`
Expected: `exit=0`, every gate prints `PASS:` (Gate 6 message now ends with `... + retraction additions changed vs main`).

- [ ] **Step 4: Lint and format the shell script change is portable (no GNU-specific extensions)**

Run: `sh -n scripts/m11-vocabulary-gates.sh; echo "exit=$?"`
Expected: `exit=0` (`sh -n` parses without executing; confirms POSIX syntax). The widened script uses only `grep -E`, `grep -vE`, `[[:space:]]`, and basic class ranges — all POSIX-portable across Windows git-bash, WSL Ubuntu, and Linux CI.

- [ ] **Step 5: Commit**

```bash
git add scripts/m11-vocabulary-gates.sh
git commit --trailer "Generated-By: claude-opus-4-7" -m "$(cat <<'EOF'
feat(m12c): widen m11 gate 6 to allow retraction additions

Add four allow-list patterns to the prose-immutability filter in
scripts/m11-vocabulary-gates.sh so the M12 retraction convention can
land its worked example. Each pattern anchors on ^+ only — deletions
under docs/changelog/*.md remain forbidden, preserving the original
M11 prose-immutability intent. Patterns mirror the M12b verifier
regex byte-for-byte (date shape, YYMMDD ref/file, anchor charset,
non-empty reason).

EOF
)"
```

---

## Task 3: Write the failing round-trip test class

**Files:**
- Modify: `tests/test_retraction_format.py`

The new test class `RetractionRoundTripTests` pins the M12c worked example byte-for-byte: it reads the live `docs/changelog/260413.md`, locates the defect and fix entry blocks by their exact heading lines, and asserts that the defect block ends with a REQ-02-valid `### Retractions` bullet pointing at the fix anchor, and that the fix block contains a `### Notes` sub-section whose only payload line is `Retracts: [defect-anchor](./260413.md#defect-anchor)`.

- [ ] **Step 1: Append the new test class to `tests/test_retraction_format.py`**

Append the following block to the bottom of `tests/test_retraction_format.py`, immediately before the `if __name__ == "__main__":` line:

```python
class RetractionRoundTripTests(unittest.TestCase):
    """REQ-09: pin the M12c worked round-trip example byte-for-byte."""

    DEFECT_HEADING = (
        "## 260413-08:39:42 - [FULL] Route create validation through "
        "shared verifier"
    )
    FIX_HEADING = (
        "## 260413-09:14:32 - [FULL] Restore verify-step retry contract"
    )
    DEFECT_ANCHOR = (
        "260413-083942---full-route-create-validation-through-shared-verifier"
    )
    FIX_ANCHOR = "260413-091432---full-restore-verify-step-retry-contract"
    CHANGELOG = REPO_ROOT / "docs" / "changelog" / "260413.md"

    def setUp(self) -> None:
        self.module = _load_module()
        self.lines = self.CHANGELOG.read_text(encoding="utf-8").splitlines()

    def _entry_block(self, heading: str) -> list[str]:
        """Return the lines belonging to the entry that opens with `heading`."""
        start = self.lines.index(heading)
        end = len(self.lines)
        for i in range(start + 1, len(self.lines)):
            if self.lines[i].startswith("## "):
                end = i
                break
        return self.lines[start:end]

    def test_defect_entry_has_retractions_subsection(self) -> None:
        block = self._entry_block(self.DEFECT_HEADING)
        self.assertIn("### Retractions", block)

    def test_defect_retraction_bullet_matches_req02(self) -> None:
        block = self._entry_block(self.DEFECT_HEADING)
        idx = block.index("### Retractions")
        bullets = [
            ln for ln in block[idx + 1 :] if ln.startswith("- ")
        ]
        self.assertEqual(len(bullets), 1, f"expected one bullet, got: {bullets}")
        bullet = bullets[0]
        match = self.module.BULLET_RE.match(bullet)
        self.assertIsNotNone(
            match, f"bullet failed REQ-02 regex: {bullet!r}"
        )
        self.assertEqual(match.group("ref"), "260413")
        self.assertEqual(match.group("file"), "260413")
        self.assertEqual(match.group("anchor"), self.FIX_ANCHOR)
        self.assertEqual(match.group("anchor2"), self.FIX_ANCHOR)

    def test_fix_entry_has_notes_subsection_with_retracts_line(self) -> None:
        block = self._entry_block(self.FIX_HEADING)
        self.assertIn("### Notes", block)
        idx = block.index("### Notes")
        payload = [
            ln
            for ln in block[idx + 1 :]
            if ln.strip() and not ln.startswith("### ")
        ]
        self.assertEqual(
            len(payload), 1, f"expected one Notes payload line, got: {payload}"
        )
        retracts_line = payload[0]
        expected = (
            f"Retracts: [260413#{self.DEFECT_ANCHOR}]"
            f"(./260413.md#{self.DEFECT_ANCHOR})"
        )
        self.assertEqual(retracts_line, expected)

    def test_defect_original_prose_is_preserved(self) -> None:
        block = self._entry_block(self.DEFECT_HEADING)
        for required in (
            "### Summary",
            "### Added",
            "### Changed",
            "### Files",
            "### QA Notes",
            "- `npm run verify`",
        ):
            self.assertIn(required, block)

    def test_fix_original_prose_is_preserved(self) -> None:
        block = self._entry_block(self.FIX_HEADING)
        for required in (
            "### Summary",
            "### Fixed",
            "### Changed",
            "### Files",
            "### QA Notes",
        ):
            self.assertIn(required, block)

    def test_live_verifier_still_exits_zero(self) -> None:
        # REQ-12: M12c additions must not regress the M12b verifier.
        self.assertEqual(self.module.main(), 0)
```

- [ ] **Step 2: Run the new test class to verify it fails**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_retraction_format.RetractionRoundTripTests -v`
Expected: `test_defect_entry_has_retractions_subsection` and `test_fix_entry_has_notes_subsection_with_retracts_line` FAIL with `ValueError: '## 260413-08:39:42 - ...' is not in list` or `assertIn` failure — because no retraction or notes block exists yet in the changelog. `test_live_verifier_still_exits_zero` PASSES (M12b baseline). The two prose-preservation tests PASS (existing prose is still present).

- [ ] **Step 3: Commit the failing test**

```bash
git add tests/test_retraction_format.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "$(cat <<'EOF'
test(m12c): add failing round-trip test for worked retraction example

Add RetractionRoundTripTests in tests/test_retraction_format.py to pin
the M12c worked example byte-for-byte: the defect entry's
### Retractions bullet must match the REQ-02 regex and point at the
fix anchor; the fix entry's ### Notes sub-section must carry exactly
one Retracts: line pointing back at the defect anchor; both entries'
original sub-sections must remain intact.

EOF
)"
```

---

## Task 4: Land the `### Retractions` sub-section on the defect entry

**Files:**
- Modify: `docs/changelog/260413.md` (append to the `260413-08:39:42` entry block)

The defect entry currently ends with its `### QA Notes` block (`- `npm run verify``) followed by a single blank line, then `## 260413-08:34:25 ...` at line 104. We append a `### Retractions` sub-section between the existing `### QA Notes` block and the blank line that separates this entry from the next.

- [ ] **Step 1: Locate the insertion point precisely**

Run: `sed -n '95,105p' docs/changelog/260413.md`
Expected: lines around 99-103 show the tail of the defect entry — `### QA Notes`, `- `npm run verify``, blank, then `## 260413-08:34:25 ...` at line 104. The exact line numbers are confirmed by Task 1 Step 3; if drift is detected, recompute from the file.

- [ ] **Step 2: Append the `### Retractions` block**

Use `Edit` to add the block after the defect entry's `### QA Notes` payload, preserving the blank-line separator between entries. The `old_string` to find (the tail of the defect entry as it currently exists) is:

```text
### QA Notes
- `npm run verify`

## 260413-08:34:25 - [FULL] Harden success verifier review fixes
```

The `new_string` that replaces it (adds `### Retractions` between the QA Notes block and the next dated heading, keeping the inter-entry blank line):

```text
### QA Notes
- `npm run verify`

### Retractions
- [2026-06-15] Retracted by [260413#260413-091432---full-restore-verify-step-retry-contract](./260413.md#260413-091432---full-restore-verify-step-retry-contract): the verify-step exit-code contract regressed and was restored by the fix entry.

## 260413-08:34:25 - [FULL] Harden success verifier review fixes
```

Note: the bullet's `reason` field is the literal one-line sentence `the verify-step exit-code contract regressed and was restored by the fix entry.` — it is non-empty, lowercase-leading, ends with a period, and contains no characters outside the REQ-02 regex's `\S.*` reason class.

- [ ] **Step 3: Re-run the round-trip test class — two cases should now pass**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_retraction_format.RetractionRoundTripTests -v`
Expected: `test_defect_entry_has_retractions_subsection`, `test_defect_retraction_bullet_matches_req02`, `test_defect_original_prose_is_preserved`, `test_live_verifier_still_exits_zero` all PASS. `test_fix_entry_has_notes_subsection_with_retracts_line` still FAILS (no `### Notes` on the fix entry yet). `test_fix_original_prose_is_preserved` PASSES.

- [ ] **Step 4: Confirm the M12b verifier still exits zero on the live tree**

Run: `python scripts/verify_retraction_format.py; echo "exit=$?"`
Expected: `exit=0`. The new bullet is REQ-02 valid (date `2026-06-15`, ref/file match `260413`, anchor text/url match, non-empty reason).

- [ ] **Step 5: Commit**

```bash
git add docs/changelog/260413.md
git commit --trailer "Generated-By: claude-opus-4-7" -m "$(cat <<'EOF'
docs(m12c): retract 260413-08:39:42 verify-step contract by 09:14:32 fix

Append a ### Retractions sub-section to the
260413-08:39:42 - [FULL] Route create validation through shared verifier
entry pointing at 260413-09:14:32, where the verify-step exit-code
contract was restored. Original Summary, Added, Changed, Files, and
QA Notes blocks are byte-for-byte unchanged.

EOF
)"
```

---

## Task 5: Land the reciprocal `### Notes` sub-section on the fix entry

**Files:**
- Modify: `docs/changelog/260413.md` (append to the `260413-09:14:32` entry block)

The fix entry currently ends with its `### QA Notes` block (`- `npm run verify``) at the top of the file. We append a `### Notes` sub-section between the existing `### QA Notes` block and the blank line that separates this entry from the next.

- [ ] **Step 1: Locate the insertion point precisely**

Run: `sed -n '20,30p' docs/changelog/260413.md`
Expected: lines 22-27 show the tail of the fix entry — `### QA Notes`, `- `npm run verify``, blank, then `## 260413-08:05:51 ...`.

- [ ] **Step 2: Append the `### Notes` block**

Use `Edit` to add the block after the fix entry's `### QA Notes` payload, preserving the blank-line separator between entries. The `old_string` is the unique tail of the fix entry:

```text
### QA Notes
- `npm run verify`

## 260413-08:05:51 - [LITE] Wire policy-backed success verifiers
```

The `new_string` (adds `### Notes` between the QA Notes block and the next dated heading):

```text
### QA Notes
- `npm run verify`

### Notes
Retracts: [260413#260413-083942---full-route-create-validation-through-shared-verifier](./260413.md#260413-083942---full-route-create-validation-through-shared-verifier)

## 260413-08:05:51 - [LITE] Wire policy-backed success verifiers
```

- [ ] **Step 3: Re-run the full round-trip test class — every case should now pass**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_retraction_format.RetractionRoundTripTests -v`
Expected: all six methods PASS.

- [ ] **Step 4: Confirm the M12b verifier still exits zero**

Run: `python scripts/verify_retraction_format.py; echo "exit=$?"`
Expected: `exit=0`. The `### Notes` block contains no `- [YYYY-MM-DD] Retracted by ...` bullet, so the verifier's bullet scanner does not visit it.

- [ ] **Step 5: Commit**

```bash
git add docs/changelog/260413.md
git commit --trailer "Generated-By: claude-opus-4-7" -m "$(cat <<'EOF'
docs(m12c): add reciprocal Retracts line to 260413-09:14:32 fix entry

Append a ### Notes sub-section to the
260413-09:14:32 - [FULL] Restore verify-step retry contract entry
carrying the REQ-05 reciprocal link back to 260413-08:39:42. Original
Summary, Fixed, Changed, Files, and QA Notes blocks are byte-for-byte
unchanged.

EOF
)"
```

---

## Task 6: Refresh the Gate 5 frozen line-number signature for 260413.md

**Files:**
- Modify: `scripts/m11-vocabulary-gates.sh:51-62`

Gate 5 compares per-file dated-heading line numbers against a frozen signature. Tasks 4 and 5 each appended 3 lines (`### Retractions\n- bullet\n\n` and `### Notes\nRetracts: ...\n\n`) inside `docs/changelog/260413.md`, shifting line numbers for every dated heading that appears after each insertion point. The signature must be recomputed and pasted into `scripts/m11-vocabulary-gates.sh` to match the new layout.

- [ ] **Step 1: Compute the new line-number list for `docs/changelog/260413.md`**

Run: `grep -nE '^##+ [0-9]{6}' docs/changelog/260413.md | cut -d: -f1 | tr '\n' ',' | sed 's/,$//'`
Expected: a new 14-number list. Line 3 (fix entry heading) does not move because Task 5 inserted INSIDE the fix entry, after its heading. Every subsequent dated heading shifts down by 3 (Task 5's 3-line `### Notes` addition). Every dated heading at or after the defect entry's original line 104 shifts down by another 3 (Task 4's 3-line `### Retractions` addition). Net per-position shift:

| original line | after Task 5 | after Task 4 |
|---:|---:|---:|
|   3 |   3 |   3 |
|  27 |  30 |  30 |
|  51 |  54 |  54 |
|  77 |  80 |  80 |
| 104 | 107 | 110 |
| 129 | 132 | 135 |
| 148 | 151 | 154 |
| 168 | 171 | 174 |
| 195 | 198 | 201 |
| 215 | 218 | 221 |
| 250 | 253 | 256 |
| 277 | 280 | 283 |
| 302 | 305 | 308 |
| 330 | 333 | 336 |

Predicted result: `3,30,54,80,110,135,154,174,201,221,256,283,308,336`. The grep is authoritative — if it disagrees with the prediction, paste whatever the grep prints (which means an insertion was not exactly 3 lines and the edits in Task 4 or Task 5 should be inspected before continuing).

- [ ] **Step 2: Update the EXPECTED block in `scripts/m11-vocabulary-gates.sh`**

Edit `scripts/m11-vocabulary-gates.sh:54`. Replace the line `docs/changelog/260413.md:3,27,51,77,104,129,148,168,195,215,250,277,302,330` with `docs/changelog/260413.md:<grep-output-from-step-1>`. Do not touch the other ten file lines in `EXPECTED` — Tasks 4 and 5 only modified `260413.md`.

- [ ] **Step 3: Run the M11 vocabulary gates end-to-end against `main`**

Run: `BASE=main sh scripts/m11-vocabulary-gates.sh; echo "exit=$?"`
Expected: every gate prints `PASS:` and the script exits 0. Specifically:
- Gate 1 vocabulary-coverage: dated == tagged (no new tagged headings added — `### Retractions` and `### Notes` are sub-section headings, not dated entry headings)
- Gate 5 ordering-preservation: signature now matches the new layout
- Gate 6 prose-immutability: the four widened allow-list patterns absorb the M12c additions
- Gate 7 line-ending portability: all touched files remain LF-only

- [ ] **Step 4: Commit**

```bash
git add scripts/m11-vocabulary-gates.sh
git commit --trailer "Generated-By: claude-opus-4-7" -m "$(cat <<'EOF'
chore(m12c): refresh m11 gate 5 line-number signature for 260413.md

The M12c worked retraction example appended a ### Retractions block
to the 260413-08:39:42 defect entry and a ### Notes block to the
260413-09:14:32 fix entry, shifting downstream dated-heading line
numbers inside docs/changelog/260413.md. Update the frozen signature
in scripts/m11-vocabulary-gates.sh Gate 5 to match the new layout;
the other ten file signatures are untouched.

EOF
)"
```

---

## Task 7: Run the full retraction test suite and lint the touched files

**Files:**
- Run: `tests/test_retraction_format.py`
- Lint: `scripts/`, `tests/test_retraction_format.py`

- [ ] **Step 1: Run the full retraction test module**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_retraction_format -v`
Expected: every test passes — the original `RetractionFormatTests` (13 cases including `test_live_changelog_tree_is_clean`) plus the new `RetractionRoundTripTests` (6 cases).

- [ ] **Step 2: Run the full project unittest discovery**

Run: `PYTHONPATH=skills/bmad-story-automator/src python -m unittest discover -s tests -v`
Expected: every pre-existing test continues to pass; the M12c additions add 6 new passing cases. No Python source under `skills/bmad-story-automator/src/` was modified, so behavior of unrelated tests is unchanged.

- [ ] **Step 3: Lint the touched files with ruff check**

Run: `python -m ruff check scripts/ tests/test_retraction_format.py`
Expected: zero violations. The only Python file touched is `tests/test_retraction_format.py`; the `scripts/` invocation also catches `scripts/verify_retraction_format.py`, which is unchanged.

- [ ] **Step 4: Verify ruff format consistency**

Run: `python -m ruff format --check scripts/ tests/test_retraction_format.py`
Expected: every file reports as already formatted. If `ruff format --check` reports drift on `tests/test_retraction_format.py`, run `python -m ruff format scripts/ tests/test_retraction_format.py` to apply formatting, re-run the unittests in Step 1 to confirm green, then continue.

- [ ] **Step 5: Commit any lint or format fixes (skip this step if none were applied)**

```bash
git add tests/test_retraction_format.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "$(cat <<'EOF'
style(m12c): apply ruff format to round-trip test class

EOF
)"
```

---

## Task 8: Verify the M11 vocabulary gates end-to-end and the M12b verifier on the live tree

**Files:**
- Run: `scripts/m11-vocabulary-gates.sh`
- Run: `scripts/verify_retraction_format.py`

- [ ] **Step 1: Run the M11 gates against `origin/main` if available**

Run: `BASE=origin/main sh scripts/m11-vocabulary-gates.sh; echo "exit=$?"` (fall back to `BASE=main` if `origin/main` is not fetched).
Expected: every gate prints `PASS:`, `exit=0`. Gate 6's `PASS:` line includes the updated message `... + retraction additions changed vs <base>`.

- [ ] **Step 2: Run the M12b retraction format verifier on the live tree**

Run: `python scripts/verify_retraction_format.py; echo "exit=$?"`
Expected: `exit=0`, no stderr.

- [ ] **Step 3: Grep for unresolved four-letter placeholder tokens (quality-gate guard)**

Run: `grep -nE '\b(TODO|FIXME|TBD)\b' CONTRIBUTING.md scripts/verify_retraction_format.py tests/test_retraction_format.py docs/changelog/260413.md docs/superpowers/plans/2026-06-15-integration-m12c-worked-retraction.md || echo "no matches"`
Expected: `no matches`.

- [ ] **Step 4: Confirm the total M12 line count is under 280**

Run: `git diff --stat origin/main...HEAD -- CONTRIBUTING.md scripts/verify_retraction_format.py scripts/m11-vocabulary-gates.sh tests/test_retraction_format.py docs/changelog/260413.md docs/changelog/260615.md docs/changelog/260616.md docs/changelog/260617.md` (fall back to `main` if `origin/main` is not fetched).
Expected: the `insertions` field is under 280 across the listed files. The M12 NFR cap is enforced cumulatively across M12a/M12b/M12c.

- [ ] **Step 5: Verify the GFM anchor slugs render correctly (precondition for NFR "anchor links must resolve when rendered on GitHub")**

The anchor strings `260413-083942---full-route-create-validation-through-shared-verifier` and `260413-091432---full-restore-verify-step-retry-contract` were derived by hand using the GFM auto-slug algorithm (lowercase → strip `[^\w\- ]` → spaces to hyphens, no hyphen collapsing). Confirm the derivation programmatically with a one-shot Python check:

```bash
python - <<'PY'
import re
def slug(text):
    text = text.lower()
    text = re.sub(r"[^\w\- ]+", "", text)
    return text.replace(" ", "-")
defect = "260413-08:39:42 - [FULL] Route create validation through shared verifier"
fix    = "260413-09:14:32 - [FULL] Restore verify-step retry contract"
print("defect:", slug(defect))
print("fix:   ", slug(fix))
PY
```

Expected output, line for line:

```
defect: 260413-083942---full-route-create-validation-through-shared-verifier
fix:    260413-091432---full-restore-verify-step-retry-contract
```

If the actual output differs from the expected anchors, do NOT proceed — the literal strings in `docs/changelog/260413.md` (Tasks 4 and 5) and `tests/test_retraction_format.py` (Task 3) must be updated to match the programmatic derivation before re-running the gates. The chosen algorithm matches `github-slugger`'s default mode, which is what GitHub's web renderer applies to changelog headings.

- [ ] **Step 6: No commit — this task is verification-only.**

---

## Task 9: Land the M12c milestone changelog entry as a new dated file

**Files:**
- Create: `docs/changelog/260617.md`
- Modify: `scripts/m11-vocabulary-gates.sh` (Gate 5 `EXPECTED` block — add one line for the new file)

Per project convention, every milestone gets a `[FULL]` / `[LITE]` / `[SKELETON]` / `[DEFERRED]` changelog entry. M12a → `260615.md`, M12b → `260616.md`, so M12c → `260617.md`. This pattern keeps each milestone in its own file, avoids mutating prior milestone entries, and lets Gate 6's exclude pathspec carve out the new file the same way it carves out the prior two. M12c is `[FULL]` because it lands implementation, tests, and all gates pass at merge time.

- [ ] **Step 1: Create `docs/changelog/260617.md` with the milestone entry**

Write the following content to `docs/changelog/260617.md`:

```markdown
# Changelog - 260617

## 260617 - [FULL] M12c worked retraction example

### Summary
Lands the real worked retraction example required by REQ-09 of `docs/superpowers/specs/2026-06-14-m12-retraction-convention.md`. Pairs the historical `260413-08:39:42 - [FULL] Route create validation through shared verifier` defect entry with the later same-day `260413-09:14:32 - [FULL] Restore verify-step retry contract` fix entry. Both halves of the round-trip are landed byte-for-byte to the REQ-02 / REQ-03 / REQ-05 forms; the M11 prose-immutability gate is widened to absorb the legitimate additions without permitting any prose deletions; new unittest coverage pins the round-trip against the M12b verifier regex.

### Added
- `### Retractions` sub-section on the `260413-08:39:42` defect entry inside `docs/changelog/260413.md`, with one REQ-02-shaped bullet pointing at the `260413-09:14:32` fix anchor.
- `### Notes` sub-section on the `260413-09:14:32` fix entry inside the same file, with one REQ-05 `Retracts:` line pointing back at the defect anchor.
- `RetractionRoundTripTests` class in `tests/test_retraction_format.py` pinning the round-trip byte-for-byte: bullet matches `BULLET_RE`, anchor strings round-trip, both entries' original `### Summary` / `### Added` / `### Changed` / `### Fixed` / `### Files` / `### QA Notes` blocks survive intact, and `verify_retraction_format.main()` still exits zero on the live tree.

### Changed
- `scripts/m11-vocabulary-gates.sh` Gate 6 (REQ-10 prose-immutability) — widened with four `^+`-anchored allow-list patterns covering `### Retractions`, `### Notes`, the REQ-02 retraction bullet form, and the `Retracts:` reciprocal-link form. Deletions under `docs/changelog/*.md` remain forbidden, preserving the original M11 intent.
- `scripts/m11-vocabulary-gates.sh` Gate 5 (REQ-11 ordering-preservation) — refreshed the frozen line-number signature for `docs/changelog/260413.md` to reflect the two 3-line sub-sections appended by Tasks 4 and 5, and extended `EXPECTED` with a `docs/changelog/260617.md:3` row for this milestone entry.
- `scripts/m11-vocabulary-gates.sh` Gate 6 exclude pathspec — extended with `:!docs/changelog/260617.md` so this wholly-new milestone entry is excluded from the historical-prose mutation check, mirroring the existing carve-out for `260615.md` and `260616.md`.

### Files
- `docs/changelog/260413.md` — appended `### Retractions` on defect entry; appended `### Notes` on fix entry; all original sub-sections byte-for-byte unchanged.
- `docs/changelog/260617.md` — this entry.
- `scripts/m11-vocabulary-gates.sh` — Gate 5 signature refresh, Gate 6 widening, Gate 6 exclude pathspec extension.
- `tests/test_retraction_format.py` — `RetractionRoundTripTests` class appended.
- `docs/superpowers/plans/2026-06-15-integration-m12c-worked-retraction.md` — implementation plan.

### QA Notes
- `python scripts/verify_retraction_format.py` exits 0 on the live tree.
- `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_retraction_format` passes 19 cases (13 pre-existing + 6 new).
- `BASE=main sh scripts/m11-vocabulary-gates.sh` exits 0 with every gate `PASS:`.
- `python -m ruff check scripts/ tests/test_retraction_format.py` and `python -m ruff format --check scripts/ tests/test_retraction_format.py` both report zero violations.
- `git diff --stat origin/main...HEAD -- CONTRIBUTING.md scripts/ tests/test_retraction_format.py docs/changelog/` reports cumulative M12 insertions under the 280-line cap.
```

- [ ] **Step 2: Extend the Gate 5 `EXPECTED` block with a row for the new file**

Edit `scripts/m11-vocabulary-gates.sh` and add the line `docs/changelog/260617.md:3` to the `EXPECTED` heredoc. The block currently ends with `docs/changelog/260616.md:3`; append `\ndocs/changelog/260617.md:3` after that line, inside the closing quote of `EXPECTED`. The result, with the previously refreshed `260413.md` row, should look like:

```sh
EXPECTED="\
docs/changelog/260401.md:3,26,61,85
docs/changelog/260412.md:3,34
docs/changelog/260413.md:3,30,54,80,110,135,154,174,201,221,256,283,308,336
docs/changelog/260414.md:3
docs/changelog/260415.md:3,33,51
docs/changelog/260506.md:3
docs/changelog/260508.md:3,25,43
docs/changelog/260517.md:3
docs/changelog/260519.md:3
docs/changelog/260615.md:3
docs/changelog/260616.md:3
docs/changelog/260617.md:3"
```

Use the actual `260413.md` line-list produced by the grep in Task 6 Step 1 if it differs from the prediction.

- [ ] **Step 3: Confirm the M11 gates pass end-to-end with the new milestone entry in place**

Run: `BASE=main sh scripts/m11-vocabulary-gates.sh; echo "exit=$?"`
Expected: `exit=0`. Specifically Gate 5 prints `PASS: REQ-11 ordering-preservation (all nine files match frozen line signature)` — note this `nine` should now read `eleven` files when `260617.md` lands; this is a cosmetic-only message and not a functional regression, but if the implementer wants to update the message to match they may do so inline (string is at `scripts/m11-vocabulary-gates.sh:80`). Gate 6 message includes `... + retraction additions changed vs main`.

- [ ] **Step 4: Confirm the M12b verifier still exits zero**

Run: `python scripts/verify_retraction_format.py; echo "exit=$?"`
Expected: `exit=0`.

- [ ] **Step 5: Commit**

```bash
git add docs/changelog/260617.md scripts/m11-vocabulary-gates.sh
git commit --trailer "Generated-By: claude-opus-4-7" -m "$(cat <<'EOF'
docs(m12c): record m12c worked retraction milestone in changelog

Add the M12c [FULL] milestone entry at docs/changelog/260617.md
documenting the worked retraction round-trip inside 260413.md, the
test class pinning it, and the gate widening that absorbs legitimate
retraction additions without weakening prose-immutability. Extend
Gate 5 EXPECTED with docs/changelog/260617.md:3 and the refreshed
260413.md signature.

EOF
)"
```

---

## Self-review summary

Spec coverage check (REQ-09 focus, with transitive verification of REQ-02/03/05/06/12):

- **REQ-09** worked example landed in a real historical entry with genuine defect-fix overlap — Task 4 (defect side) + Task 5 (fix side) in `docs/changelog/260413.md`.
- **REQ-02** retraction bullet format `- [YYYY-MM-DD] Retracted by [YYMMDD#anchor](./YYMMDD.md#anchor): <one-line reason>` — Task 4 Step 2 (literal bullet) and Task 3 Step 1 (regex assertion via `self.module.BULLET_RE`).
- **REQ-03** original prose / bullet list / file references of the retracted entry not modified — Task 4 only appends a new sub-section; Task 3's `test_defect_original_prose_is_preserved` pins all original sub-section headings.
- **REQ-05** fix entry carries `Retracts: [YYMMDD#anchor]` under `### Notes` (or equivalent) — Task 5 Step 2 (literal block) and Task 3's `test_fix_entry_has_notes_subsection_with_retracts_line` (byte-for-byte assertion).
- **REQ-06** worked example showing both halves of the round-trip — the M12a fictional example already lives in `CONTRIBUTING.md`; M12c lands the real round-trip inside `docs/changelog/260413.md` and exposes both halves through Tasks 4 and 5.
- **REQ-12** M11 contributor-guide grep gate continues to pass — Task 2 (Gate 6 widening) and Task 6 (Gate 5 signature refresh) jointly satisfy this, validated in Task 8 Step 1.

Placeholder scan: no `TBD`, `TODO`, `<placeholder>`, `<fill-in>`, or "implement later" remain. Every code block, edit instruction, and commit message is fully specified.

Type/identifier consistency: `BULLET_RE` is consumed in Task 3 as `self.module.BULLET_RE` and is the actual top-level identifier in `scripts/verify_retraction_format.py:12`. `_load_module()` and `REPO_ROOT` are reused from the existing test module's top of file. Anchor slug strings `260413-083942---full-route-create-validation-through-shared-verifier` and `260413-091432---full-restore-verify-step-retry-contract` are used identically in Tasks 3, 4, 5, and the M12c changelog entry — no drift.
