# M11 — Changelog vocabulary

## Context

M11 is a docs-only milestone of the bmad-automator port that introduces and retroactively enforces a controlled vocabulary of four scope tags for every entry under `docs/changelog/`. The four tags are `FULL`, `LITE`, `SKELETON`, and `DEFERRED`, and they describe how completely a change was carried through across spec, implementation, tests, and verification. M11 modifies `CONTRIBUTING.md` to require contributors to tag every new changelog entry with exactly one of those four labels, defines the meaning of each tag in plain prose, retroactively audits the nine existing changelog files spanning `260401.md` through `260519.md`, and inserts the appropriate tag at every entry heading found in those files. M11 has no Python source impact — it depends on no other milestone, ships no new modules, and changes no behavior of the `story_automator` package. The risk profile is LOW because the only artifacts touched are `CONTRIBUTING.md` and Markdown changelog files. M11 unblocks downstream readability for the operator and for automated changelog-driven release tooling planned in later milestones by giving every historical and future entry a machine-greppable scope tag. The companion implementation plan will record the exact insertion points for each retroactive tag and the auditor's rationale for the chosen label per entry.

## Out of scope

M11 does not introduce or modify any Python module, any dataclass, any telemetry event type, or any test under `tests/`. M11 specifically does not touch `skills/bmad-story-automator/src/story_automator/core/telemetry_events.py` (which is M01's output and remains frozen here), nor does it touch `skills/bmad-story-automator/src/story_automator/core/common.py`, `skills/bmad-story-automator/src/story_automator/commands/orchestrator.py`, `skills/bmad-story-automator/src/story_automator/commands/orchestrator_epic_agents.py`, `skills/bmad-story-automator/src/story_automator/core/tmux_runtime.py`, or `skills/bmad-story-automator/src/story_automator/commands/state.py`. The wiring of the `TelemetryEmitter` into existing log sites is M02's responsibility; the cost-capture path through `orchestrator_parse.py` is M03's responsibility; HMAC chaining of the event stream is M04's responsibility; the regex-frontmatter replacement in `commands/state.py` is M05's responsibility; tmux spawn and completion log sites are touched by M06 and M07; failure-classification consumers are M07; later runtime verification milestones are M08, M09, and M10. The rewrite of `SECURITY.md` is M14's responsibility and is not bundled here. M11 also does not retroactively rewrite the prose summaries of historical changelog entries — only the tag annotation is added — and does not delete, merge, or re-order any historical entry.

## Functional requirements

1. REQ-01 the contributor guide at `CONTRIBUTING.md` must be updated to require every new entry under `docs/changelog/` to carry exactly one scope tag drawn from the closed set `FULL`, `LITE`, `SKELETON`, `DEFERRED`.
2. REQ-02 `CONTRIBUTING.md` must define `FULL` as a change shipped with spec, implementation, tests, and verification all complete and passing all quality gates at merge time.
3. REQ-03 `CONTRIBUTING.md` must define `LITE` as a change shipped with implementation and tests but with reduced spec depth or deferred non-blocking polish, where every quality gate still passes at merge time.
4. REQ-04 `CONTRIBUTING.md` must define `SKELETON` as a change that lands structure or scaffolding only (for example a module stub or a directory tree) with no behavioral wiring and no test coverage requirement beyond import compilation.
5. REQ-05 `CONTRIBUTING.md` must define `DEFERRED` as a change recorded for traceability where the underlying work has been intentionally postponed to a later milestone, the entry must name the deferring milestone, and no quality-gate enforcement applies to deferred entries.
6. REQ-06 `CONTRIBUTING.md` must specify the exact insertion syntax for the tag, which must place the tag in square brackets immediately after the timestamp and hyphen on the entry heading line (for example `## 260519-12:00:00 - [FULL] Title goes here`).
7. REQ-07 `CONTRIBUTING.md` must state that exactly one tag is required per entry; multiple tags on a single entry must be rejected at review time, and entries without any tag must be rejected at review time.
8. REQ-08 every existing changelog entry across the nine files `docs/changelog/260401.md`, `docs/changelog/260412.md`, `docs/changelog/260413.md`, `docs/changelog/260414.md`, `docs/changelog/260415.md`, `docs/changelog/260506.md`, `docs/changelog/260508.md`, `docs/changelog/260517.md`, and `docs/changelog/260519.md` must be audited and assigned exactly one of the four tags by direct inspection of the entry's described scope.
9. REQ-09 the audit must insert the chosen tag in the exact heading syntax specified by REQ-06 at every level-two and level-three heading that introduces a distinct dated entry; informational sub-sections such as `### Summary`, `### Added`, `### Changed`, `### Removed`, `### Files`, and `### QA Notes` must not receive tags.
10. REQ-10 the retroactive audit must not modify the prose body, the bullet content, the file list, or the QA notes of any historical entry; only the heading line of each dated entry may change.
11. REQ-11 the retroactive audit must preserve the original chronological order of entries within each file and across files; no entry may be moved, merged, split, deleted, or re-dated.
12. REQ-12 a grep across `docs/changelog/*.md` for the regex `^##+ \d{6}` must return a count of matches equal to the count of matches for the regex `\[(FULL|LITE|SKELETON|DEFERRED)\]` on the same heading lines after M11 completes.
13. REQ-13 the four allowed tag strings must appear in `CONTRIBUTING.md` exactly once each as fenced inline code in the definition list so they are machine-greppable as a closed vocabulary reference.

## Non-functional requirements

- The vocabulary definitions in `CONTRIBUTING.md` must be written in plain English with no acronyms beyond those already established in the repository (BMAD, PR, CI, QA).
- The `CONTRIBUTING.md` diff introduced by M11 must remain under one hundred added lines so the review burden stays low.
- The retroactive tag insertion must produce a clean unified diff on each of the nine changelog files, with no whitespace-only churn, no trailing-whitespace introduction, and no line-ending changes.
- The audit reasoning for each retroactive tag assignment must be recorded in the M11 implementation plan so future contributors can reproduce or contest the choice.
- The four-tag vocabulary must remain closed; adding a fifth tag in a future milestone must require a follow-up spec and is explicitly forbidden inside M11.
- All four tag strings must be uppercase ASCII letters only so they are unambiguous under grep with `-F` and stable across platforms.

## Quality gates

- The lint gate passes under `python -m ruff check skills/bmad-story-automator/src/story_automator/` with zero violations because M11 introduces no Python source changes.
- The format gate passes under `python -m ruff format --check skills/bmad-story-automator/src/story_automator/` with zero files needing reformat.
- The unittest gate passes under `PYTHONPATH=skills/bmad-story-automator/src python -m unittest discover -s tests` with zero failing tests, because M11 must not regress any existing test.
- The coverage gate remains at or above 85 percent on previously covered modules under `python -m coverage run --source=skills/bmad-story-automator/src/story_automator -m unittest discover -s tests && python -m coverage report -m --fail-under=85`.
- The import-allowlist gate passes: a grep across `skills/bmad-story-automator/src/story_automator/` for new imports beyond stdlib plus `filelock` and `psutil` returns zero matches, because M11 adds no Python imports.
- The module-size gate passes: every Python module under `skills/bmad-story-automator/src/story_automator/` remains at five hundred or fewer source lines.
- The vocabulary-coverage gate passes: a grep across `docs/changelog/*.md` for dated entry headings returns the same count as a grep for the four allowed tag strings on those same heading lines.
- The closed-vocabulary gate passes: a grep across `docs/changelog/*.md` for any bracketed uppercase token of three to nine ASCII letters on a heading line returns only the four tokens `FULL`, `LITE`, `SKELETON`, `DEFERRED` and no others.
- The contributor-guide gate passes: a grep of `CONTRIBUTING.md` returns at least one occurrence of each of the four tag strings as inline code.
- All quality gates run on Windows git-bash, WSL Ubuntu, and Linux CI without modification.