# CLAUDE.md

## Project

**bmad-story-automator** — portable BMAD `bmad-story-automator` skill/plugin bundle. Python port of `bma-d/bmad-story-automator-go`. Distributed as an npm package, a Claude Code plugin, and a local marketplace catalog entry.

## Tech stack

- Python 3.11+ runtime (no extra deps beyond stdlib plus `filelock` and `psutil`)
- Node entrypoint (`bin/bmad-story-automator`) and npm packaging
- tmux for child-session orchestration
- Bash smoke tests (`scripts/smoke-test.sh`)
- Markdown changelog under `docs/changelog/`
- Linting/formatting via `ruff`; tests via `unittest`; coverage via `coverage`

## Module map

- `skills/bmad-story-automator/` — installable main skill, contains the Python runtime
  - `src/story_automator/core/` — runtime building blocks (telemetry, tmux runtime, policy, verifiers, common helpers)
  - `src/story_automator/commands/` — CLI command implementations (orchestrator, orchestrator_parse, state, tmux, validate_story_creation, basic, etc.)
  - `src/story_automator/adapters/` — adapters such as tmux
  - `scripts/story-automator` — installed helper CLI wrapper
- `skills/bmad-story-automator-review/` — bundled adversarial code-review skill (no Python)
- `tests/` — `unittest` discovery root
- `bin/bmad-story-automator` — npm bin entrypoint
- `install.sh` — installer copying skill folders into a target project's skill roots
- `scripts/smoke-test.sh` — `npm pack` + install smoke harness
- `docs/` — operator docs, plans, specs, changelog
  - `docs/changelog/*.md` — dated changelog entries, controlled vocabulary `[FULL]`, `[LITE]`, `[SKELETON]`, `[DEFERRED]` per M11
  - `docs/superpowers/specs/` — milestone specs
  - `docs/superpowers/plans/` — milestone implementation plans
- `.claude-plugin/plugin.json` and `.claude-plugin/marketplace.json` — Claude plugin and marketplace manifests

## Conventions

- Conventional Commits for every commit
- Every commit carries a `Generated-By:` git trailer naming the model
- Branch naming `bma-d/<milestone-slug>` for milestone work
- One PR per milestone; milestones numbered M01..MNN
- Docs-only milestones never modify Python sources, tests, or telemetry types
- Changelog entry heading syntax: `## YYMMDD[-HH:MM:SS] - [TAG] Title` where `TAG` is one of the closed four-tag vocabulary
- File size soft limit: 500 LOC per Python module
- Run `npm run verify` (test:python, pack:dry-run, test:cli, test:smoke) before any release-style commit

## Hard guardrails

- Do NOT add Python imports beyond stdlib, `filelock`, `psutil` without an explicit spec waiver
- Do NOT add a fifth changelog vocabulary tag inside M11 — that requires a separate follow-up spec
- Do NOT touch `skills/bmad-story-automator/src/story_automator/core/telemetry_events.py` outside its owning milestone (M01)
- Do NOT rewrite the prose body, bullet content, file list, or QA notes of any historical changelog entry — only dated heading lines may change during retroactive audits
- Do NOT modify `### Summary`, `### Added`, `### Changed`, `### Fixed`, `### Removed`, `### Files`, `### QA Notes`, or any other sub-section heading when applying tags — tags only attach to dated entry headings matching `^##+ \d{6}`
- Do NOT introduce trailing whitespace, whitespace-only churn, or line-ending changes when editing Markdown
- Do NOT delete, merge, reorder, split, or re-date any historical changelog entry
- Quality gates must remain portable across Windows git-bash, WSL Ubuntu, and Linux CI without modification
- All four tag strings are uppercase ASCII letters only
