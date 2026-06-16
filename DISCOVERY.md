# Step 0 Discovery — bmad-automator packaging

Date: 2026-06-14
Operator: mira5557373

## Decision: HYBRID (Node + Python)

- `package.json` present at repo root ✓
- `pyproject.toml` only inside `skills/bmad-story-automator/`
- `bin/bmad-story-automator` is a Node shim that refuses `process.platform === 'win32'` at line 37-40
- The Node bin wraps a bash `install.sh` which sets up the Python `story_automator` package

## Implications for the port

- WSL Ubuntu-26.04 is mandatory for any runtime/CLI verification (M02, M05, M06a-b, M07, M10 Phase E)
- Python milestone code lives under `skills/bmad-story-automator/src/story_automator/`
- Tests run on Windows too (pytest is cross-platform) — only the bin shim and integration tmux tests need WSL
- npm scripts (`npm run pack:dry-run`, `npm run test:smoke`) require Node — available on Windows

## Source layout reference

- Python package: `skills/bmad-story-automator/src/story_automator/`
- Step files (skill markdown): `skills/bmad-story-automator/steps-c/`, `steps-e/`, `steps-v/`
- Data / prompts: `skills/bmad-story-automator/data/`
- Tests: `tests/` (unittest, ~13 files)
- Docs: `docs/changelog/<YYMMDD>.md`
