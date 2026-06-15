# M12 — Retraction-as-changelog convention

## Context

M11 introduced the closed `FULL` / `LITE` / `SKELETON` / `DEFERRED` scope vocabulary in `CONTRIBUTING.md` and retroactively tagged the nine existing changelog files. M12 builds on that contributor-guide foundation by codifying a **retraction-as-changelog discipline**: when a later release fixes a defect that was originally documented as working in an earlier changelog entry, the earlier entry must be edited in place with a dated forward-link to the fix entry. This preserves the chronological audit trail (no rewriting of history), surfaces known-bad-then-fixed states to future readers of the older entry, and prevents the silent rot that occurs when a defect fix lives only in the newer entry.

## Out of scope

M12 must not modify any Python source module, must not introduce new contributor obligations beyond the retraction convention itself, must not alter the M11 vocabulary tags, must not re-tag entries beyond adding retraction footnotes when a real retroactive fix is documented, and must not edit prose bodies or file lists of historical changelog entries beyond appending a new `Retractions` sub-section. Tooling automation (a `retract` CLI helper or pre-commit hook) is explicitly deferred to a follow-up milestone. The convention applies only to entries under `docs/changelog/`; it must not be extended to README, design docs, or specs.

## Functional requirements

1. REQ-01 a new `Retractions` section must be added to `CONTRIBUTING.md` immediately after the M11 vocabulary section, with a level-2 heading exactly `## Retractions` and a body of at least three paragraphs explaining purpose, syntax, and timing.
2. REQ-02 the syntax for a retraction footnote must be specified as a bullet under a `### Retractions` sub-heading appended to the original changelog entry, with the exact form `- [YYYY-MM-DD] Retracted by <fix-entry-link>: <one-line reason>` where `<fix-entry-link>` is a markdown anchor link of the form `[YYMMDD#anchor](./YYMMDD.md#anchor)`.
3. REQ-03 the convention must explicitly state that the original prose body, bullet list, and file references of the retracted entry must NOT be modified — only the new `### Retractions` sub-heading and its bullets are added.
4. REQ-04 the convention must state that retractions must NEVER be applied to entries that pre-date this M12 commit by more than nine months, to bound the audit-and-edit obligation on contributors.
5. REQ-05 the convention must require that the fix entry itself (the newer changelog entry that contains the actual repair commits) reference the retraction it triggers, via a `Retracts: [YYMMDD#anchor]` line under the fix entry's `### Notes` or equivalent metadata block.
6. REQ-06 a worked example must be added inline in `CONTRIBUTING.md` showing both halves of a retraction round-trip: the modified historical entry with its `### Retractions` bullet and the fix entry with its `Retracts:` metadata line.
7. REQ-07 the convention must specify exactly one rule for the case where a fix later turns out to be incomplete: the original retraction bullet stays in place, and a second retraction bullet with a new date and second fix-entry-link is appended.
8. REQ-08 the convention must specify that retraction bullets are NOT scope-tagged with the M11 vocabulary (`FULL` / `LITE` / `SKELETON` / `DEFERRED`); tags apply to top-level changelog entries only.
9. REQ-09 a worked retraction example must be landed in a historical entry under `docs/changelog/` chosen for genuine defect-fix overlap with a later entry; the example must satisfy REQ-02, REQ-03, REQ-05, and REQ-06 byte-for-byte.
10. REQ-10 a tests directory script at `scripts/verify_retraction_format.py` must validate every `### Retractions` block across `docs/changelog/*.md` against the REQ-02 regex and exit non-zero on any malformed bullet.
11. REQ-11 the verifier script must be added as a documented contributor gate in `CONTRIBUTING.md` with the exact invocation `python scripts/verify_retraction_format.py` and an expected exit-zero behavior on a clean tree.
12. REQ-12 the convention must reaffirm that the M11 contributor-guide grep gate must continue to pass after the new `## Retractions` section is added — the verifier script must not introduce a regression in the vocabulary gate.
13. REQ-13 the convention must add a brief note that the retraction convention applies regardless of which scope tag (`FULL`, `LITE`, `SKELETON`, `DEFERRED`) the original entry carried; even `SKELETON` entries can be retracted if the skeleton itself was promised but never landed.

## Non-functional requirements

- The M12 diff must touch no Python source modules under `skills/bmad-story-automator/src/story_automator/` or `tests/`; the change is documentation and contributor-tooling only, so the Python quality gates remain trivially green.
- The M12 diff must add fewer than 200 lines to `CONTRIBUTING.md` and must add the verifier script as fewer than 80 lines of pure-stdlib Python with a single test in `tests/test_retraction_format.py`.
- The convention must be written so it remains correct under all three line-ending policies (Windows CRLF, Unix LF, macOS LF) without per-line conversion.
- The worked retraction example must compile as valid GitHub-flavored markdown — anchor links must resolve when the file is rendered on GitHub.
- The contributor-facing prose must avoid jargon beyond BMAD, PR, CI, and the four M11 scope tags; no new acronyms.
- The verifier script must complete in under one second on the full historical changelog set and must use only the Python standard library.

## Quality gates

- `python scripts/verify_retraction_format.py` exits zero on the M12 head commit.
- `python -m unittest tests.test_retraction_format` passes with the new test suite covering the regex, the round-trip example, and the non-fix-entry case.
- `python -m ruff check scripts/ tests/test_retraction_format.py` passes with zero violations.
- `python -m ruff format --check scripts/ tests/test_retraction_format.py` passes with zero files needing reformat.
- The M11 vocabulary gate (`scripts/verify_changelog_vocabulary.py` or equivalent) continues to exit zero — no regression on the M11 contract.
- A grep for unresolved four-letter placeholder tokens across `CONTRIBUTING.md`, `scripts/verify_retraction_format.py`, and `tests/test_retraction_format.py` returns no matches.
- The M12 diff against `bma-d/m11-changelog-vocabulary` adds fewer than 280 total lines across all touched files.
