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

## Soak archive

The repository preserves paired A/B soak runs under `_bmad-output/soak/` for
downstream calibration and review. The canonical layout is:

```
_bmad-output/soak/<YYYY-MM-DD>/<arm>/
  telemetry.jsonl  # M02 emitter output, line-delimited JSON events
  report.md        # human-readable narrative, YAML frontmatter required
  config.json      # arm parameters (arm, seed, model, concurrency, notes)
```

- `<YYYY-MM-DD>` is an ISO-8601 calendar date that parses via
  `datetime.date.fromisoformat`.
- `<arm>` is a non-empty slug matching the regular expression
  `[a-z0-9._-]+`; the verifier rejects anything else.
- `telemetry.jsonl` is the immutable per-run event log; every non-empty line
  must be a JSON object with at least `event_type` (string) and `ts` (string).
- `report.md` must begin with a YAML frontmatter block delimited by `---`
  lines containing the keys `arm`, `date`, `run_id`, `git_sha`, `started_at`,
  and `ended_at`. `started_at` must be ISO-8601; `ended_at` may temporarily
  be the literal `pending` between seeding and finalization.
- `config.json` is a JSON object containing the keys `arm` (str), `seed`
  (int), `model` (str), `concurrency` (int), and `notes` (str). The
  top-level `arm` value must equal the directory name.

### Commands

- Seed a new arm directory:

  ```
  python scripts/seed_soak_dir.py --date 2026-06-13 --arm control
  ```

  Re-running the command against an existing populated arm is a no-op: the
  seeder never overwrites a non-empty file.

- Verify an archive:

  ```
  python scripts/verify_soak_format.py _bmad-output/soak/
  ```

  Exit code is 0 on success, 1 on validation failure (one finding per line on
  stderr, sorted by path), and 2 on usage error.

### Placeholder tokens

Soak archives committed to this repository must not contain unresolved
uppercase four-letter bracketed placeholder tokens (the conventional review
markers of the form `\[[A-Z]{4}\]`) inside `report.md` or `config.json`.
`scripts/verify_soak_format.py` flags any such occurrence as a validation
failure, and CI additionally greps `CONTRIBUTING.md` to keep this guidance
itself free of the same markers.

## Reporting Bugs

Include:
- OS
- Python version
- Node version
- BMAD skill layout under `.claude/skills`
- exact command run
- exact error output
