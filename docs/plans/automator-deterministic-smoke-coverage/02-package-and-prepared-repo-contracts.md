# Phase 02 - Package And Prepared Repo Contracts

## Clean Context Start

Before doing this phase, read [README.md](./README.md), this phase file, [TODO/phase-02.md](./TODO/phase-02.md), [gate-map.md](./gate-map.md), [implementation-notes.md](./implementation-notes.md), and relevant earlier entries in [handoff-log.md](./handoff-log.md).

Do not read later phase files or later TODO files as acceptance criteria for this phase.

## Goal

Harden the package and prepared-repo smoke contract so packed tarballs, installed files, dependency skill roots, and prepared `gunz` layout fail deterministically when installer drift occurs.

This phase is release-blocking. A prepared repo smoke result is not trustworthy until it proves that `.smoke/gunz` installed the current packed tarball rather than a stale same-shape install.

## Inputs

- [scripts/prepare-smoke-test.py](../../../scripts/prepare-smoke-test.py)
- [scripts/smoke_prep/](../../../scripts/smoke_prep)
- [scripts/smoke-test.sh](../../../scripts/smoke-test.sh)
- [scripts/run-smoke-automator.py](../../../scripts/run-smoke-automator.py)
- [scripts/run-smoke-dev-loop.py](../../../scripts/run-smoke-dev-loop.py)
- [package.json](../../../package.json)
- [install.sh](../../../install.sh)

## Implementation Steps

1. Add a deterministic `npm run pack:assert` gate for required package files and forbidden generated/cache files using `npm pack --dry-run --json`.
2. Capture and assert packed tarball identity in the same `npm run pack:assert` gate, or a separately named `npm run pack:identity` gate if implementation size warrants it, using `npm pack --json --pack-destination <tmp>`: package name, version, filename, integrity or shasum, generated tarball path, and selected checksums.
3. Create or reuse a shared installed-file manifest for the real packed install into `.smoke/gunz`.
4. Assert `.smoke/gunz` installed the current packed tarball, not a stale same-shape install: installed version surfaces match tarball metadata, selected installed files have checksums matching the tarball contents, and prep report records the tarball identity.
5. Compare narrow installed-file checksums against the extracted tarball for `SKILL.md`, `scripts/story-automator`, policy JSON, parse contracts, prompt templates, `pyproject.toml`, review `contract.json`, and version surfaces.
6. Extend `smoke:prepare` layout verification beyond helper `--help` to cover runtime source, policy JSON, parse/prompt files, templates, review skill contract, module metadata, and dependency skill entrypoints.
7. Add a deterministic installed-root check for supported runtime roots when feasible: `.claude`, `.agents`, and `.codex`. If external BMAD install cannot prepare all roots, mark missing roots as `blocked` or `spec-only` in the coverage baseline.
8. Use stable JSON and checksum assertions; do not accept terminal-output-only `npm pack` success as package proof.
9. Update [gate-map.md](./gate-map.md) with package-content, installed-identity, installed-manifest, and prepared-repo gates.

## Verification

- Run the package content assertion.
- Run `npm run smoke:prepare -- --reset`.
- Run `npm run smoke:run`.
- Run `npm run smoke:dev-loop`.
- Run `git diff --check`.

## Exit Criteria

- The prepared external repo verifies the installed automator package identity and checksums, not just local source fixtures or same-shape installed files.
- Package content assertions catch missing required files and unexpected generated files.
- Unsupported or unavailable install roots are explicitly classified instead of silently ignored.
- `npm run pack:assert` is fast enough for the future default `npm run verify`; prepared repo install checks remain explicit unless Phase 06 proves CI/runtime budget.
- Phase 02 handoff entry appended.

## Implementation Notes Requirements

Record any installer-root limitations, BMAD Method pinning decisions, and package manifest tradeoffs in [implementation-notes.md](./implementation-notes.md).

## Handoff Requirements

Append a Phase 02 entry to [handoff-log.md](./handoff-log.md) with exact smoke prep command output summary, tarball/package details, installed manifest path, and next recommended command.
