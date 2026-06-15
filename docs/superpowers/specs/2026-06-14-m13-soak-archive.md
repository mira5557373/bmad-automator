# M13 — soak-archive

## Context

The bmad-automator port has, in earlier milestones, produced two streams of evidence that operators need to compare across experimental conditions. M01 defined a typed event base and thirteen concrete subclasses (StoryStarted, StoryCompleted, StoryFailed, StoryDeferred, RetryAttempt, EscalationTriggered, ReviewCycle, RetroFired, TmuxSessionSpawned, TmuxSessionCompleted, TmuxSessionCrashed, CostCharged, BudgetAlert) plus UnknownEvent and a `parse_event` helper at `skills/bmad-story-automator/src/story_automator/core/telemetry_events.py`. M02 then wired a locked JSONL `TelemetryEmitter` and a streaming `TelemetryReader` (with `cost_by_epic`, `attempts_by_story`, and `retro_inputs` aggregations) into the orchestrator and tmux runtime so every run drops a parseable `telemetry.jsonl` trail. M13 codifies the on-disk layout that holds those trails for paired A/B soak runs, under `_bmad-output/soak/<YYYY-MM-DD>/<arm>/`, alongside a human-readable `report.md` and a machine-readable `config.json` describing the arm. The archive is consumed downstream by the M08 calibration loop (which will sweep `attempts_by_story` against `cost_by_epic` across arms) and by reviewers comparing retro narratives. This milestone touches no Python source under `skills/`; it ships only repository plumbing, two small standalone stdlib scripts, a test, and a CONTRIBUTING.md addition.

## Out of scope

This milestone does not implement the calibration loop itself — M08 owns reading the archive, fitting parameters, and emitting recommendations. It does not produce or rotate telemetry events; M01 and M02 own event types and the emitter. It does not implement HMAC verification of the archive (M04 owns audit), and it does not implement archive pruning or cold-storage tiering (M09 owns lifecycle). It does not synthesize report.md content from telemetry (a future "auto-report" milestone, tentatively M06, will do that). It does not gate CI on the presence of an archive; the gate added here only runs when an archive directory exists. It does not standardize cross-arm statistical comparison (M10 owns the soak compare report).

## Functional requirements

REQ-01 The repository must define the canonical soak archive root as `_bmad-output/soak/` relative to the repo root, and per-run subdirectories must follow `_bmad-output/soak/<YYYY-MM-DD>/<arm>/` where `<arm>` is a non-empty slug of `[a-z0-9._-]+`.

REQ-02 Each `<arm>` directory must contain exactly three required files at its top level: `telemetry.jsonl`, `report.md`, and `config.json`. Additional files are permitted but must be ignored by the verifier.

REQ-03 The script `scripts/verify_soak_format.py` must expose a `main(argv: list[str] | None = None) -> int` entry point that accepts a positional path argument (defaulting to `_bmad-output/soak/`) and returns process exit code 0 on success, 1 on validation failure, and 2 on usage error.

REQ-04 `verify_soak_format.py` must validate that every `<YYYY-MM-DD>` directory name parses as an ISO-8601 calendar date via `datetime.date.fromisoformat` and that every `<arm>` directory contains the three required files; missing files must be reported one path per line on stderr.

REQ-05 `verify_soak_format.py` must validate that `report.md` begins with a YAML-style frontmatter block delimited by `---` lines containing at least the keys `arm`, `date`, `run_id`, `git_sha`, `started_at`, and `ended_at`; `started_at` and `ended_at` must parse via `datetime.datetime.fromisoformat`.

REQ-06 `verify_soak_format.py` must validate that `config.json` parses as a JSON object containing at least the keys `arm` (str), `seed` (int), `model` (str), `concurrency` (int), and `notes` (str); the top-level `arm` value must equal the directory name.

REQ-07 `verify_soak_format.py` must validate that `telemetry.jsonl` is line-delimited UTF-8 where every non-empty line decodes as a JSON object with at least an `event_type` (str) and `ts` (str) field; the verifier must not import from `story_automator` and must use only `json`, `pathlib`, `datetime`, `argparse`, `sys`, and `re`.

REQ-08 The script `scripts/seed_soak_dir.py` must expose a `main(argv: list[str] | None = None) -> int` entry point accepting `--date`, `--arm`, and optional `--root` (default `_bmad-output/soak/`) and must create the target directory plus stub `telemetry.jsonl` (empty), `config.json` (a JSON object with the M13 required keys populated with sentinel defaults), and `report.md` (frontmatter populated with provided values and an empty body).

REQ-09 `seed_soak_dir.py` must import `iso_now`, `compact_json`, `write_atomic`, and `ensure_dir` from `story_automator.core.common` when invoked from within an installed checkout, and must fall back to inlined equivalents only when those imports fail, so that re-running it is idempotent and never clobbers an existing non-empty file.

REQ-10 The frontmatter `started_at` and `ended_at` values written by `seed_soak_dir.py` must be produced via `iso_now()` at seed time for `started_at` and left as the literal string `pending` for `ended_at` until the operator updates it.

REQ-11 `CONTRIBUTING.md` must be extended with a "Soak archive" section that documents the directory layout, the purpose of each of the three required files, the frontmatter schema, the slug constraints on `<arm>`, and the commands `python scripts/seed_soak_dir.py` and `python scripts/verify_soak_format.py`.

REQ-12 The CONTRIBUTING.md section must explicitly forbid committing soak archives that contain unresolved four-letter placeholder tokens (the conventional bracketed markers reviewers reject) in `report.md` or `config.json`, and the verifier must flag any such occurrence as a validation failure.

REQ-13 The test module `tests/test_soak_format.py` must use `unittest.TestCase`, must construct fixture archives under `tempfile.TemporaryDirectory`, and must cover: (a) a valid arm passes, (b) missing each required file fails, (c) malformed frontmatter fails, (d) telemetry line lacking `event_type` fails, (e) `seed_soak_dir.main` produces a directory that `verify_soak_format.main` accepts, and (f) re-running `seed_soak_dir.main` against an existing populated arm leaves files untouched.

REQ-14 Both scripts must begin with `from __future__ import annotations`, must declare a `if __name__ == "__main__": raise SystemExit(main())` guard, and must use PEP 604 union syntax (e.g., `list[str] | None`) for any annotated parameter or return type.

## Non-functional requirements

- Cross-platform: both scripts and the test suite must run unchanged on Windows git-bash, WSL, and Linux; paths must be constructed via `pathlib.Path` and never via `os.sep` string concatenation, and the verifier must treat `\r\n` and `\n` line endings as equivalent when reading `telemetry.jsonl` and `report.md`.
- Dependency floor: no new third-party imports beyond the existing stdlib plus `filelock` and `psutil` baseline; the verifier in particular must remain pure stdlib so it can run in a minimal CI image.
- Module size: `scripts/verify_soak_format.py` and `scripts/seed_soak_dir.py` must each remain at or below 500 source lines, and `tests/test_soak_format.py` must remain at or below 500 source lines.
- Line-ending portability: files written by `seed_soak_dir.py` must use `\n` line endings on all platforms by opening files with `newline=""` plus explicit `\n` joins, so that archives committed from Windows match archives committed from Linux byte-for-byte.
- Typing posture: every module must begin with `from __future__ import annotations` and must use PEP 604 union syntax throughout; no `typing.Optional` or `typing.Union` imports.
- Determinism: `verify_soak_format.py` must emit findings sorted by path so that diffing two CI runs over the same tree produces stable output.

## Quality gates

- `ruff check scripts/verify_soak_format.py scripts/seed_soak_dir.py tests/test_soak_format.py` must report zero findings.
- `ruff format --check scripts/verify_soak_format.py scripts/seed_soak_dir.py tests/test_soak_format.py` must report no reformatting needed.
- `python -m unittest tests.test_soak_format` must pass with zero failures and zero errors.
- `coverage run -m unittest tests.test_soak_format && coverage report --fail-under=85` must succeed for both scripts.
- Import-allowlist grep: `grep -E "^(from|import) " scripts/verify_soak_format.py` must show only `json`, `pathlib`, `datetime`, `argparse`, `sys`, and `re` (plus `__future__`); any other module is a gate failure.
- Module size: `wc -l scripts/verify_soak_format.py scripts/seed_soak_dir.py` must each report a line count at or below 500.
- Self-verification: `python scripts/seed_soak_dir.py --date 2026-06-13 --arm gate-check --root /tmp/m13-gate && python scripts/verify_soak_format.py /tmp/m13-gate` must exit 0, proving the seed and verify scripts agree on the schema.
- CONTRIBUTING.md must remain free of unresolved four-letter placeholder tokens, verified by a grep gate in CI.