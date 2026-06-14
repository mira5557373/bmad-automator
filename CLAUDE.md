# CLAUDE.md

## Project

**bmad-story-automator** — Python-parity port of the BMAD story automator. Drives the create / dev / QA / review / retro story-build cycle via resumable tmux orchestration. Distributed as an npm package that installs Python skills into a host project.

## Tech Stack

- Python 3.11+ (target: 3.11/3.12/3.13)
- Standard library only for runtime modules unless a module spec opts in to a dependency. Allowed third-party deps so far: `filelock`.
- Tests: `unittest` (no pytest). Discover with `python -m unittest discover -s tests`.
- Lint/format: `ruff check` and `ruff format --check`.
- Packaging: `hatchling` (Python wheel), `npm pack` (distribution).
- Node ≥ 18 for the installer/smoke scripts (`scripts/`, `bin/`).

## Module Map

- `skills/bmad-story-automator/src/story_automator/`
  - `__init__.py` — version pin
  - `__main__.py` — `python -m story_automator` entrypoint
  - `cli.py` — top-level CLI dispatch
  - `core/` — pure utility modules (no CLI side effects)
    - `common.py` — `iso_now`, `compact_json`, `write_atomic`, helpers
    - `runtime_policy.py` — policy load / merge / snapshot
    - `runtime_layout.py`, `frontmatter.py`, `epic_parser.py`, `story_keys.py`, …
    - `tmux_runtime.py` — tmux session orchestration
  - `commands/` — CLI subcommands
    - `state.py` — story-state frontmatter mutations
    - `orchestrator.py` — escalation handling
    - `orchestrator_epic_agents.py` — retro-agent dispatch
  - `adapters/` — external-tool adapters
- `tests/` — repo-root unittest suite. Run with `PYTHONPATH=skills/bmad-story-automator/src python -m unittest discover -s tests`.
- `scripts/` — bash installer / smoke helpers.
- `docs/superpowers/specs/` — milestone specs.
- `docs/superpowers/plans/` — implementation plans (per milestone).

## Conventions

- Every Python module starts with `from __future__ import annotations`.
- Public functions and dataclasses carry concise docstrings (inputs, outputs, raised exceptions).
- Errors raised from a subsystem use a subsystem-specific exception class (e.g. `PolicyError`); cross-subsystem callers should not catch bare `Exception`.
- Atomic file writes go through `core.common.write_atomic`.
- Timestamps via `core.common.iso_now` (UTC, second precision, `Z` suffix).
- JSON canonicalisation via `core.common.compact_json` (no whitespace, `ensure_ascii=False`).
- Tests are `unittest.TestCase` subclasses in `tests/test_<name>.py`. No pytest fixtures.
- Frequent commits using Conventional Commits (`feat:`, `fix:`, `test:`, `chore:`, `docs:`, `spec(<area>):`).

## Hard Guardrails

- **No third-party runtime deps** beyond what a module's spec explicitly authorises. `psutil` is forbidden everywhere.
- **No secrets in logs / repr / exception messages.** Modules handling secret material (audit key, future tokens) MUST omit raw secret bytes from any user-visible surface.
- **No silent failure paths.** Catching and swallowing exceptions without re-raising or logging via the structured channel is a bug.
- **Atomic writes only** for state files — never partial overwrites.
- **TDD is mandatory** for every code change: write the failing test, watch it fail, write the minimal code to pass, commit.
- **Do not refactor outside the milestone surface.** If a spec scopes a single file, do not touch siblings except for the integrations the spec authorises.
- **Module size budget for audit-class code: ≤ 500 source lines** (enforced by test).

## Workflow

- Specs live under `docs/superpowers/specs/`. Plans live under `docs/superpowers/plans/`.
- One milestone = one plan = one branch. Branch names match the milestone slug (e.g. `bma-d/m04-audit-trail`).
- Commit on every passing TDD step; never bundle "write test + write impl" into one commit.
- Run `npm run verify` (which runs `test:python`, `pack:dry-run`, `test:cli`, `test:smoke`) before opening a PR.
