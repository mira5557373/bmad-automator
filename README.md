# bmad-story-automator

Install the BMAD **story-automator** self-contained skills into a BMAD project.

`bmad-story-automator` orchestrates [BMAD-Method](https://github.com/bmad-code-org/BMAD-METHOD)
story execution end to end: it drives the plan → implement → verify → review → commit
loop for each story in an epic, spawning and supervising per-story agent sessions in
`tmux` child panes, tracking progress in a durable orchestration-state document, and
emitting a structured telemetry ledger for every run. It ships three ways — as an **npm
package**, a **Claude Code plugin**, and a local marketplace catalog entry — and the
runtime is a dependency-light Python package (`story_automator`).

## Prerequisites

- **Node** ≥ 18 (to run the installer / `npx`)
- **Python** ≥ 3.11 (the runtime execs `python3 -m story_automator`)
- **bash** and **tmux** (child-session orchestration; tmux is required on the host that runs stories)
- Python deps beyond the stdlib: `filelock`, `psutil`

## Install

Into the current directory (a BMAD project root):

```bash
npx bmad-story-automator
```

Or into an explicit project root:

```bash
npx bmad-story-automator /path/to/bmad-project
```

The installer copies the skill folders into the project's supported skill roots
(`.claude/skills`, `.agents/skills`, `.codex/skills`). It is a pure file copy; an existing
install is backed up before being replaced.

## Usage

After install, the helper CLI lives under each skill root, e.g.
`.claude/skills/bmad-story-automator/scripts/story-automator`. It exposes one flat command
surface (parsing, state, tmux, orchestrator helpers, agent config, verification & telemetry,
basic utilities). See [docs/cli-reference.md](docs/cli-reference.md) for the full command list.

```bash
story-automator --version
story-automator --help
```

Day to day, orchestration is driven by the bundled skill workflow rather than by direct CLI
calls; the CLI is the control plane the workflow shells out to.

## Architecture

- `skills/bmad-story-automator/` — the installable skill + Python runtime
  - `src/story_automator/core/` — runtime building blocks (telemetry, tmux runtime, policy, verifiers, atomic IO, run identity/liveness)
  - `src/story_automator/commands/` — CLI command implementations
- `skills/bmad-story-automator-review/` — bundled adversarial code-review skill
- `bin/bmad-story-automator` — npm bin entrypoint (installer launcher)
- `install.sh` — installer that copies skill folders into a project
- `docs/` — operator documentation

Security posture and reporting are documented in [SECURITY.md](SECURITY.md).

## Development

```bash
npm run lint:python   # ruff (pinned ruleset)
npm run test:python   # unittest suite
npm run verify        # lint + tests + pack dry-run + CLI + smoke test
```

Conventions: Conventional Commits, one PR per milestone, a `Generated-By:` trailer on each
commit. Quality gates stay portable across Windows git-bash, WSL Ubuntu, and Linux CI.

## License

MIT
