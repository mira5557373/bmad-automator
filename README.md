# bmad-story-automator

Portable BMAD `bmad-story-automator` skill/plugin bundle — a Python port of `bma-d/bmad-story-automator-go`. Distributed as both a Claude Code plugin and an npm package.

## Overview

`bmad-story-automator` packages the BMAD story-automation workflow as a portable skill that can be installed into any Claude Code environment. The Node `bin/` shim wraps a bash `install.sh` that sets up the Python `story_automator` package under the host's `.claude/skills` directory.

- **Version:** 1.15.0
- **Current branch:** `bma-d/sw-port-foundation`
- **Active milestone:** M01 — Event types (wedge atom) for the typed-telemetry substrate
- **Platform support:** Linux, macOS, WSL Ubuntu (the Node shim explicitly refuses `win32`)

## Quickstart

### Prerequisites

- Python ≥ 3.11
- Node.js (for the install shim)
- POSIX shell (Linux / macOS / WSL — Windows native is not supported by the shim)

### Install

```bash
npm install -g bmad-story-automator
bmad-story-automator
```

### Run tests

```bash
npm run test:python   # full unittest suite (also pytest -q compatible)
npm run test:smoke    # smoke test
npm run verify        # full verify pipeline
```

### Lint & format

```bash
python -m ruff check skills/bmad-story-automator/src tests
python -m ruff format --check skills/bmad-story-automator/src tests
```

### Coverage

```bash
python -m coverage run --source=skills/bmad-story-automator/src \
  -m unittest discover -s tests
python -m coverage report -m --fail-under=85
```

### Build

```bash
npm run build:python
npm run pack:dry-run
```

## Architecture

```
.
├── skills/bmad-story-automator/
│   ├── pyproject.toml             # name=story-automator, py >=3.11
│   ├── src/story_automator/
│   │   ├── __init__.py            # __version__ = "1.15.0"
│   │   ├── __main__.py
│   │   ├── cli.py                 # CLI entry point
│   │   ├── adapters/              # external adapters
│   │   ├── commands/              # orchestrator, retro, state, tmux, …
│   │   └── core/                  # shared helpers
│   │       ├── common.py          # iso_now(), compact_json(), write_atomic(), run_cmd()
│   │       ├── agent_config.py    # @dataclass conventions reference
│   │       ├── tmux_runtime.py    # tmux session orchestration
│   │       ├── telemetry_events.py # M01 typed-telemetry data definitions
│   │       └── runtime_*.py
│   ├── steps-c/, steps-e/, steps-v/   # skill markdown
│   └── data/                          # prompts / templates
├── tests/                         # ~14 unittest files at the repo root
├── docs/
│   ├── superpowers/
│   │   ├── specs/                 # specs + design docs
│   │   └── plans/                 # implementation plans
│   └── changelog/<YYMMDD>.md
├── bin/bmad-story-automator       # Node shim (refuses Windows)
├── install.sh                     # bash installer driven by the Node shim
└── package.json                   # npm scripts: test:python, build:python, pack:dry-run, verify
```

### Dependency policy

Stdlib only, plus the allowlisted dependencies:

- `filelock`
- `psutil`

Adding any third-party package outside this allowlist requires operator approval. The allowlist is enforceable via `grep` against `pyproject.toml` per spec REQ-11.

### CI matrix

| OS      | Python versions     |
| ------- | ------------------- |
| Ubuntu  | 3.11, 3.12, 3.13    |
| macOS   | 3.11, 3.12, 3.13    |

Spec REQ-01 also calls for 3.14 once stable.

### Telemetry substrate — M01 status

The current milestone introduces the `Event` data class with a deterministic JSON-line serializer and the 13 concrete typed event classes spanning the BMAD story lifecycle:

- `Event.to_dict` injects `event_type` from a class-level constant
- `Event.to_json_line` delegates to the shared `compact_json` helper
- `iso_now` and `compact_json` are re-exported from `story_automator.core.common`
- Byte-level deterministic guard ensures stable output ordering across runs and platforms
- 13 concrete events: `StoryStarted`, `StoryCompleted`, `StoryFailed`, `StoryDeferred`, `RetryAttempt`, `EscalationTriggered`, `ReviewCycle`, `RetroFired`, `TmuxSessionSpawned`, `TmuxSessionCompleted`, `TmuxSessionCrashed`, `CostCharged`, `BudgetAlert`
- `UnknownEvent` forward-compatibility fallback for unrecognized `event_type` strings
- `parse_event(line) -> Event` with a strict schema: `ValueError` on missing `event_type` or non-object top-level JSON, `json.JSONDecodeError` on malformed input, `TypeError` on typed-event field mismatch

**Out of scope for M01:** `TelemetryEmitter`, `TelemetryReader`, wiring existing log sites, cost-capture path, HMAC chaining, and typed enums for `severity` / `error_class` / `reason` / `phase`. Those land in M02–M07.

## Contributing

### Python conventions

- `from __future__ import annotations` at the top of every module
- Plain `@dataclass` — not `frozen`, not `slots`
- PEP 604 union types (`str | None`, never `Optional[str]`)
- Imports grouped: stdlib → third-party → local
- snake_case for Python attributes and JSON keys
- Files under ~500 LOC where practical

### Shared helpers

Import from `story_automator.core.common` — do **not** duplicate:

- `iso_now()`
- `compact_json()`
- `write_atomic()`
- `ensure_dir()`
- `run_cmd()`

### Testing

- `unittest.TestCase` subclasses (also discoverable by `pytest -q`)
- Mixed `assert` and `self.assertEqual` is acceptable (matches existing style)
- Tests must run cross-platform: Windows git-bash, WSL Ubuntu, Linux CI
- No subprocess invocations, no tmux dependencies, no network access in unit tests

Runtime-verification gates (M02 / M05 / M06 / M07 / M10) require WSL Ubuntu-26.04 because of tmux. M01 itself is pure data and runs on any platform.

### Commits

Use Conventional Commits with scopes:

- `feat(scope):` — new feature
- `fix(scope):` — bug fix
- `test(scope):` — tests only
- `refactor(scope):` — no behavior change
- `docs(scope):` — documentation
- `style(scope):` — formatting only
- `build(scope):` — build system

Add a `Generated-By` trailer where applicable. One commit per task step where reasonable.

### Hard guardrails

- Never add a third-party Python dependency outside the allowlist without operator approval
- Never introduce subprocess calls, network access, or tmux dependencies in unit tests
- Never modify `bin/bmad-story-automator`, `install.sh`, or the `pyproject.toml` allowlist without flagging the change
- Never skip pre-commit hooks (no `--no-verify`) — investigate failures and fix the underlying issue
- Never force-push to `main` or to any branch with an open PR upstream
- Always preserve the pure skill-install behavior under `.claude/skills`
- Always use Conventional Commits and verify cross-platform compatibility before finalizing a quality gate

### Spec / plan locations

- M01 spec:   `docs/superpowers/specs/2026-06-14-m01-event-types.md`
- M01 design: `docs/superpowers/specs/2026-06-14-m01-event-types-design.md`
- M01 plan:   `docs/superpowers/plans/2026-06-14-m01-event-types.md`
- Discovery:  `DISCOVERY.md` (HYBRID Node + Python decision)
