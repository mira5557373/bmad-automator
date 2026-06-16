# CLAUDE.md — Project Guidelines

## Project

**Name:** bmad-story-automator (Python port)

**Goal:** Portable BMAD `bmad-story-automator` skill/plugin bundle. Python port of `bma-d/bmad-story-automator-go`. Packaged as both a Claude Code plugin and an npm package; the Node `bin/` shim wraps a bash `install.sh` that sets up the Python `story_automator` package.

**Current branch:** `bma-d/sw-port-foundation` (the sw-port worktree). Active milestone: **M01 — Event types (wedge atom)** for the typed-telemetry substrate.

## Tech stack

- Python 3.11+ (`requires-python = ">=3.11"` in pyproject.toml). CI runs on 3.11, 3.12, 3.13 (Ubuntu + macOS). Spec REQ-01 also requires 3.14.
- Stdlib only, plus `filelock` and `psutil` (the dependency allowlist).
- Tests: `unittest.TestCase` via `python -m unittest discover -s tests` (per `npm run test:python`). The M01 spec also requires `pytest -q` compatibility — `pytest` discovers `unittest.TestCase` natively.
- Lint/format: `ruff` (no project-wide ruff config found yet; spec assumes one exists — flag in gap analysis).
- Coverage: stdlib `coverage` package (operator-installed, not a project dep).
- Build: `hatchling` (`build:python` script via `python3 -m build`).
- Node shim: `bin/bmad-story-automator` is a Node script that refuses `process.platform === 'win32'`.

## Module map

```
.
├── skills/bmad-story-automator/
│   ├── pyproject.toml          # name=story-automator, py >=3.11
│   ├── src/story_automator/
│   │   ├── __init__.py         # __version__ = "1.15.0"
│   │   ├── __main__.py
│   │   ├── cli.py              # CLI entry
│   │   ├── adapters/           # external adapters
│   │   ├── commands/           # orchestrator, retro, state, tmux, etc.
│   │   └── core/               # shared helpers
│   │       ├── common.py       # iso_now(), compact_json(), write_atomic(), run_cmd(), ...
│   │       ├── agent_config.py # @dataclass conventions reference
│   │       ├── tmux_runtime.py # tmux session orchestration
│   │       ├── runtime_*.py
│   │       └── (no __init__.py — namespace by convention)
│   ├── steps-c/, steps-e/, steps-v/  # skill markdown
│   └── data/                          # prompts/templates
├── tests/                       # ~13 unittest files at the repo root
├── docs/
│   ├── superpowers/
│   │   ├── specs/              # sw-lint-passing specs + design docs
│   │   └── plans/              # implementation plans
│   └── changelog/<YYMMDD>.md
├── bin/bmad-story-automator    # Node shim (refuses Windows)
├── install.sh                  # bash installer driven by the Node shim
└── package.json                # npm scripts: test:python, build:python, pack:dry-run, verify
```

## Conventions

- **Python source:** `from __future__ import annotations` at the top. Plain `@dataclass` (not `frozen`, not `slots`). PEP 604 union types (`str | None`, not `Optional[str]`). Imports grouped stdlib → third-party → local.
- **Shared helpers:** Import `iso_now`, `compact_json`, `write_atomic`, `ensure_dir`, `run_cmd` from `story_automator.core.common` — DO NOT duplicate.
- **Naming:** snake_case Python attributes, snake_case JSON keys.
- **Tests:** `unittest.TestCase` subclasses. Mixed `assert` and `self.assertEqual` is acceptable (matches existing style). Cross-platform — no tmux dependency in unit tests, no subprocess invocations.
- **Commits:** Conventional Commits (`feat(scope):`, `fix(scope):`, `test(scope):`, `refactor(scope):`, `docs(scope):`, `style(scope):`, `build(scope):`). One commit per task step where reasonable. Add `Generated-By` trailer.
- **File size:** keep files under roughly 500 LOC when practical (per `CONTRIBUTING.md`).
- **Cross-platform:** Tests must run on Windows git-bash, WSL Ubuntu, and Linux CI without modification. No tmux-dependent logic in unit tests. The Node `bin/` shim is the only Windows-blocking surface — Python tests should never touch it.
- **Runtime verification gates** (M02 / M05 / M06 / M07 / M10): require **WSL Ubuntu-26.04** because of tmux. M01 itself is pure data and runs on any platform.

## Hard guardrails

- **Never** add a third-party Python dependency outside the spec's allowlist (`stdlib + filelock + psutil`) without operator approval. Spec REQ-11 is enforceable via grep.
- **Never** introduce subprocess calls, network access, or tmux dependencies in unit tests.
- **Never** modify the Node `bin/` shim, `install.sh`, or the `pyproject.toml` allowlist without flagging it as a behavioral change.
- **Never** create planning, decision, or analysis documents speculatively. Specs and plans live under `docs/superpowers/specs/` and `docs/superpowers/plans/` only.
- **Never** skip pre-commit hooks (no `--no-verify`). Investigate hook failures; fix the underlying issue.
- **Never** force-push to `main` or to a branch that has been opened as a PR upstream.
- **Always** preserve the pure skill-install behavior under `.claude/skills`; treat old `_bmad/bmm` story-automator install paths as migration-only backups.
- **Always** use Conventional Commits.
- **Always** verify cross-platform compatibility before finalizing a quality gate — Windows git-bash is the operator's primary shell.
- **Out of scope for M01:** `TelemetryEmitter`, `TelemetryReader`, wiring existing log sites, cost-capture path, HMAC chaining, typed enums for `severity`/`error_class`/`reason`/`phase`, timestamp-format validation. Those are M02+.

## Test runner commands

| Action | Command |
|---|---|
| Full Python test suite | `npm run test:python` (= `PYTHONPATH=skills/bmad-story-automator/src python3 -m unittest discover -s tests`) |
| Single M01 test file (Windows) | `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.test_telemetry_events -v` |
| Lint | `python -m ruff check <paths>` |
| Format check | `python -m ruff format --check <paths>` |
| Coverage | `python -m coverage run --source=<src> -m unittest tests.<file> && python -m coverage report -m --fail-under=85` |
| Smoke | `npm run test:smoke` |
| Full verify | `npm run verify` |
| Pack dry-run | `npm run pack:dry-run` |

## Spec / plan locations

- M01 spec: `docs/superpowers/specs/2026-06-14-m01-event-types.md`
- M01 design: `docs/superpowers/specs/2026-06-14-m01-event-types-design.md`
- M01 plan: `docs/superpowers/plans/2026-06-14-m01-event-types.md`
- Discovery: `DISCOVERY.md` (HYBRID Node + Python decision)

## Out-of-scope (anti-scope creep)

Each milestone has tightly bounded scope. Do not pull forward work from later milestones. M01 is data definitions + parsing protocol only. The emitter is M02. The cost-capture path is M03. HMAC chaining is M04. Failure-classification consumers are M07.
