# Contributing

## Scope

This repository packages the BMAD story-automator workflow payload plus the Python runtime used by the installed workflow.

## Before Opening A PR

- keep changes scoped; avoid unrelated cleanup
- keep files under roughly 500 LOC when practical
- preserve pure skill install behavior under `.claude/skills`
- treat old `_bmad/bmm` story-automator install paths as migration-only backups
- avoid adding dependencies unless clearly justified
- run:
  - `npm run pack:dry-run`
  - `npm run test:smoke`
  - `PYTHONPATH=skills/bmad-story-automator/src python3 -m story_automator --help`
  - `python scripts/verify_retraction_format.py`

The `python scripts/verify_retraction_format.py` gate is expected to exit 0 on a clean tree; a non-zero exit indicates a malformed `### Retractions` bullet under `docs/changelog/` that must be fixed before opening the PR.

## PR Notes

- use Conventional Commits
- describe user-facing behavior changes
- mention install-path or workflow-path changes explicitly
- call out any payload or runtime files copied from upstream BMAD sources

## Changelog Scope Tags

Every new entry under `docs/changelog/` must carry exactly one scope tag from this closed four-tag vocabulary: FULL, LITE, SKELETON, or DEFERRED. The tag goes inside square brackets immediately after the timestamp and the hyphen on the entry's heading line, for example:

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

## Retractions

When a later release fixes a defect that was originally documented as working in an earlier `docs/changelog/` entry, the earlier entry must be edited in place with a dated forward-link to the fix entry. This preserves the chronological audit trail — no rewriting of history — while surfacing known-bad-then-fixed states to future readers of the older entry. The convention exists so that a contributor opening an older changelog entry to understand past behavior cannot be silently misled by prose that was accurate at the time but became wrong after a later fix landed.

The retraction is recorded as a new `### Retractions` sub-section appended to the original entry. The original prose body, bullet list, file references, and QA notes of the historical entry must NOT be modified — only the new `### Retractions` sub-heading and its bullets are added. Each bullet uses the exact form:

```text
- [YYYY-MM-DD] Retracted by [YYMMDD#anchor](./YYMMDD.md#anchor): <one-line reason>
```

The date in square brackets is the retraction date (the date the bullet is authored, not the date of the original entry). The link target is a GitHub-flavored-markdown anchor of the form `[YYMMDD#anchor](./YYMMDD.md#anchor)` pointing at the dated fix entry under `docs/changelog/`. Retraction bullets are NOT scope-tagged with the M11 vocabulary: the closed tags `FULL`, `LITE`, `SKELETON`, and `DEFERRED` apply only to top-level dated changelog entry headings, never to retraction bullets.

Retractions must NEVER be applied to entries that pre-date this convention commit by more than nine months, to bound the audit-and-edit obligation on contributors. The convention applies regardless of which scope tag (`FULL`, `LITE`, `SKELETON`, or `DEFERRED`) the original entry carries; even a `SKELETON` entry can be retracted if the skeleton itself was promised but never landed. The fix entry that triggers a retraction must reciprocally reference the entry it retracts via a `Retracts: [YYMMDD#anchor]` line under the fix entry's `### Notes` block (or under any equivalent metadata block the entry uses). When a fix later turns out to be incomplete, the original retraction bullet stays in place and a second retraction bullet with a new date and a new fix-entry-link is appended below the first — earlier retraction bullets are never deleted, edited, or re-dated.

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

## Pre-commit hook (optional but recommended)

This repository ships an opt-in pre-commit gate that runs the full
`unittest` suite, `ruff check`, and the M11 changelog vocabulary gate
before every commit. It is **not** auto-installed — neither by
`npm install` nor by `install.sh`. Operators opt in once per clone:

```
./scripts/install-hooks.sh
```

This sets the project-local `core.hooksPath` to `.githooks/`. To skip
the gate for a single commit, prefer the git-native escape:

```
git commit --no-verify ...
```

For ad-hoc batches (e.g., a long rebase) the env-var escape is:

```
BMAD_SKIP_PRECOMMIT=1 git commit ...
```

To uninstall:

```
./scripts/uninstall-hooks.sh
```

The hook does not source `.envrc` or `.env`; direnv users may need to
arrange their venv activation independently. The hook autodetects
`python3` / `python` / `py` and a venv-local `ruff` if available.

## Reporting Bugs

Include:
- OS
- Python version
- Node version
- BMAD skill layout under `.claude/skills`
- exact command run
- exact error output
