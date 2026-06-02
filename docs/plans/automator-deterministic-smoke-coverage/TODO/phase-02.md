# Phase 02 TODO - Package And Prepared Repo Contracts

## Scope

Use this checklist only for Phase 02. Do not use later phase TODO files as acceptance criteria.

## Checklist

- [x] Read [README.md](../README.md), [02-package-and-prepared-repo-contracts.md](../02-package-and-prepared-repo-contracts.md), this TODO file, [gate-map.md](../gate-map.md), and relevant earlier entries in [handoff-log.md](../handoff-log.md).
- [x] Keep [implementation-notes.md](../implementation-notes.md) current while implementing.
- [x] Add package dry-run JSON assertions.
- [x] Add packed tarball identity assertions for name, version, filename, integrity or shasum.
- [x] Add prepared-repo installed manifest verification.
- [x] Add installed-version and installed-file checksum checks against the current tarball.
- [x] Ensure package checks use `npm pack --dry-run --json` and `npm pack --json` data, not terminal-output-only assertions.
- [x] Make `pack:assert` suitable for the future default `npm run verify`.
- [x] Classify unsupported install roots explicitly.
- [x] Update [gate-map.md](../gate-map.md) for Phase 02 gates.
- [x] Run the phase verification checks.
- [x] Append the Phase 02 handoff entry before ending.
