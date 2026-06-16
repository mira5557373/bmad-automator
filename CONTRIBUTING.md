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

## Reporting Bugs

Include:
- OS
- Python version
- Node version
- BMAD skill layout under `.claude/skills`
- exact command run
- exact error output
