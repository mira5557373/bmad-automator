# CLAUDE.md — bmad-story-automator (Python port)

## Project

`bmad-story-automator` is the Python port of `bma-d/bmad-story-automator-go`. It packages a
Claude/Codex skill bundle plus a Python helper runtime that drives an autonomous orchestration
loop over a BMAD project's stories: create story, implement, automate/test, adversarial code
review, commit, retrospective. The runtime spawns short-lived child agents in tmux sessions
with permission prompts deliberately suppressed.

## Tech stack

- Python 3.11+ (target runtime).
- Standard library only, plus `filelock` and `psutil` (third-party allowlist).
- `tmux` as the child-session host.
- Node/npm packaging: `package.json` ships the skills directory as an installable `npx`
  payload (`bmad-story-automator`).
- Markdown + YAML as the source of truth for workflow state (`sprint-status.yaml`, story
  files, the orchestrator state doc).

## Module map

- `skills/bmad-story-automator/` — installable skill bundle (SKILL.md, workflow.md, data,
  templates, helper scripts).
- `skills/bmad-story-automator/src/story_automator/` — Python runtime.
  - `__init__.py` — `__version__` only.
  - `__main__.py`, `cli.py` — CLI entrypoint.
  - `commands/` — high-level command handlers (`orchestrator.py`,
    `orchestrator_epic_agents.py`, `orchestrator_parse.py`, `state.py`, `tmux.py`,
    `agent_config_cmd.py`, `validate_story_creation.py`, `basic.py`).
  - `core/` — shared helpers (`common.py` for `iso_now`/`compact_json`/`write_atomic`,
    `tmux_runtime.py` for the `claude --dangerously-skip-permissions` launch, plus
    frontmatter, sprint, runtime policy, story keys, stop hooks, success verifiers,
    workflow paths, etc.).
  - `adapters/` — runtime adapters.
- `skills/bmad-story-automator-review/` — bundled review skill.
- `tests/` — `unittest` suite, discovered with `python -m unittest discover -s tests -t .`.
- `docs/` — operator and contributor docs (`how-it-works.md`, `cli-reference.md`,
  `versioning.md`, etc.), `docs/changelog/YYMMDD.md`, `docs/superpowers/specs/` and
  `docs/superpowers/plans/` for milestone specs and plans.
- Root: `SECURITY.md`, `CONTRIBUTING.md`, `README.md`, `LICENSE`, `install.sh`,
  `package.json`, `bin/bmad-story-automator`.

## Conventions

- Conventional Commits (e.g., `docs(m14): ...`, `feat(m04): ...`).
- TDD: write the failing test first; minimal implementation second; verify; commit.
- Keep every Python module under `skills/bmad-story-automator/src/story_automator/` at or
  below 500 lines of source. Top-level markdown like `SECURITY.md` is also held to 500
  lines per its spec.
- `ruff check` and `ruff format --check` are gate-clean against
  `skills/bmad-story-automator/src/story_automator tests`.
- Line coverage on `skills/bmad-story-automator/src/story_automator/` stays at or above
  85 percent under `coverage run -m unittest discover` then `coverage report`.
- Tests run with `python -m unittest discover -s tests -t .` from the repo root.
- Plain US English in operator-facing docs; expand acronyms (LLM, BMAD, REQ) on first
  use; no emoji, no decorative ASCII, no trailing whitespace.

## Hard guardrails

- Do not add third-party Python dependencies beyond the stdlib + `filelock` + `psutil`
  allowlist.
- Do not silently widen the trust surface. The orchestrator launches child agents with
  permission prompts suppressed (Claude `--dangerously-skip-permissions`, Codex
  `approval_policy=never` / `sandbox=workspace-write` / `--full-auto`); any change that
  affects this posture must be flagged in `SECURITY.md` and `CONTRIBUTING.md` in the same
  PR.
- Do not bypass `git` hooks (`--no-verify`, `--no-gpg-sign`).
- Do not edit upstream BMAD sources under `external/BMAD-METHOD` from automator
  milestones.
- Use Conventional Commits; do not skip the per-milestone changelog entry under
  `docs/changelog/YYMMDD.md` when one is required by the milestone.
- Documentation milestones (e.g., M11, M14) must not change Python source.
