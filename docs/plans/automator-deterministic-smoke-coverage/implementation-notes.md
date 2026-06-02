# Automator Deterministic Smoke Coverage Implementation Notes

## Purpose

This file is the running user-facing implementation record. Keep decisions, spec gaps, required changes, tradeoffs, deviations, risks, and user-relevant context here.

This is separate from [handoff-log.md](./handoff-log.md). Use the handoff log for next-agent continuity: what to read, exact commands, blockers, and next recommended actions.

## Note Template

```md
## YYYY-MM-DD - phase/session

### Context

- What part of the spec or implementation this note concerns.

### Decision, Change, Or Tradeoff

- What was decided or changed.
- Why it was necessary.

### User Impact

- What the user should know.
- Follow-up needed, or `None`.
```

## Notes

## 2026-06-02 - phase 06 gate integration

### Context

- Phase 06 required final gate wiring, explicit heavy-smoke separation, and readiness review.

### Decision, Change, Or Tradeoff

- Updated `npm run verify` to run the fast deterministic local gate set: `test:python`, `version:check`, `pack:assert`, `test:cli`, `smoke:contracts`, `smoke:modes`, and `test:smoke`.
- Added `npm run smoke:deterministic-full` as the explicit reset/network-heavy pre-release gate: `smoke:prepare -- --reset`, `smoke:run`, `smoke:dev-loop`, and `smoke:finish-loop`.
- Kept `smoke:finish-loop` out of default `verify` even though it is local, because Phase 06 target verify was already broad and the release-wrapper gate captures finish-loop readiness explicitly.
- Deterministic readiness still excludes live provider/auth behavior, rate limits, trust prompts, outages, semantic quality of generated implementation/reviews/retrospectives, and interactive UX beyond helper-backed effects.

### User Impact

- `npm run verify` is now the default fast confidence gate.
- `npm run smoke:deterministic-full` is the fuller pre-release smoke with prepared repo reset and package/install identity proof.

## 2026-06-02 - phase 05 finish-loop coverage

### Context

- Phase 05 required deterministic coverage for automate, review, commit/finalize, retrospective, execution-complete, wrapup, and host commit isolation.

### Decision, Change, Or Tradeoff

- Added `npm run smoke:finish-loop` using `scripts/run-smoke-finish-loop.py` and a temp git-backed BMAD-style fixture.
- The runner seeds a three-story, two-epic state and proves automate `done` plus non-blocking `skip`, incomplete review diagnostics, review completion, smoke-repo-only commits, sprint/story source-of-truth finalization, epic completion helpers, retro-agent and retro build-cmd coverage, state-recorded skipped retrospective semantics, continuation into a later epic, execution-complete/wrapup transitions, final metrics, learnings output, and marker removal.
- Commit isolation is enforced by a runner target guard that rejects the host repo before `commit-story`, then host HEAD/status is compared before and after the smoke. The runner also supports an explicit `--allow-unsafe-repo` manual override for debugging.
- The report keeps durable diagnostics under `.smoke/finish-loop-diagnostics/`, including a state document copy and temp smoke repo `git-log.txt`, because the working temp repo is deleted after command exit.
- Retrospective execution remains simulated as skipped deterministic output; no live retrospective agent is spawned. This matches the deterministic boundary while proving the non-blocking state/log contract.

### User Impact

- Finish-loop readiness now has a fast local gate that can prove commit safety without mutating the host checkout.
- Phase 06 can promote `smoke:finish-loop` into the deterministic full smoke or verify gates.

## 2026-06-02 - phase 04 mode coverage

### Context

- Phase 04 required deterministic coverage for create startup, resume, validate, edit, marker lifecycle, and direct state/artifact assertions.

### Decision, Change, Or Tradeoff

- Added `npm run smoke:modes` using `scripts/run-smoke-modes.py` and a temp BMAD-style `.agents` fixture.
- The mode smoke asserts invalid range empty-selection behavior, stop-hook configured/pending-trust/failure states, sprint-status present/missing preconditions, state discovery, explicit path resume summary, no-incomplete fresh-create fallback, workflow-derived resume/edit menus and route hints, resume branch-equivalent helper checks, marker path/heartbeat/block/allow behavior, state validation, structure issue reporting, source-of-truth mismatch surfacing through the shared review verifier, and helper-backed edit save/discard/edit-more contracts.
- State/artifact assertions include rendered agent config, progress row metrics, action-log deltas, complexity/agents artifact paths, edit-time artifact path updates, simulated child dev log, compact mode report, parsed marker JSON, heartbeat mutation, and dynamic `.gitignore` entries.
- Fixture writes to story files and `sprint-status.yaml` are simulated child workflow output for source-of-truth checks; they are not treated as orchestrator-owned mutations.
- Fully interactive edit menu prompts and docs-path prompt behavior remain workflow-only because no deterministic helper exists for them yet. Phase 04 covers deterministic helper-backed branches and records route hints instead of trying to automate conversational waits.

### User Impact

- Resume/validate/edit now have fast local deterministic coverage suitable for future `verify` promotion.
- Prepared `.smoke/gunz` create/dev checks remain explicit external-flow gates and are not required by `smoke:modes`.

## 2026-06-02 - phase 03 runtime helper contracts

### Context

- Phase 03 required deterministic helper contract coverage before broader lifecycle smokes.

### Decision, Change, Or Tradeoff

- Added `npm run smoke:contracts` as a focused unittest gate over parser, monitor, runner, build-cmd, state-update, runtime-policy, state metadata, marker/root, and success-verifier contract suites.
- Added `tests/test_runtime_helper_contracts.py` for missing parser subprocess, monitor terminal-state, build-cmd branch, runner edge-state, and `tmux-wrapper spawn` runner-mode coverage.
- Kept production helper code unchanged; the phase exposed assertion wording drift only (`state file unreadable` for missing state files).
- `parse-output`'s JSON decode branch is defensive because `extract_json_line` already filters invalid JSON before returning a candidate line; the enforced contract is no-json or schema-invalid failure payloads.

### User Impact

- Helper drift now fails through a named fast gate instead of being hidden behind broad smoke success.
- `monitor-session` terminal failures still usually exit `0`; callers must read JSON `final_state`, `exit_reason`, and `output_verified`.

## 2026-06-02 - phase 02 package and prepared repo contracts

### Context

- Phase 02 required package tarball identity and prepared-repo installed-file proof.

### Decision, Change, Or Tradeoff

- Added `npm run pack:assert` using `npm pack --dry-run --json` plus `npm pack --json --pack-destination <tmp>`.
- `pack:assert` now checks required package files, executable modes, forbidden generated/cache files, package identity, tarball SHA256, and selected tarball member checksums.
- `smoke:prepare` now writes `.smoke/PACKAGE_IDENTITY.json` and `.smoke/INSTALLED_AUTOMATOR_MANIFEST.json`.
- Prepared `.smoke/gunz` install verification compares selected installed `.claude/skills` files against the current tarball checksums.
- `.agents/skills` and `.codex/skills` are classified as `spec-only` for prepared gunz because BMAD prep uses `--tools claude-code`, which only creates complete `.claude/skills` dependency entrypoints.

### User Impact

- Prepared smoke runs now fail if `.smoke/gunz` is still using a stale same-version tarball.
- The Phase 02 verification caught and replaced a stale installed workflow (`1.12.0`) with the current `1.15.0` tarball install.

## 2026-06-02 - phase 01 baseline and version inputs

### Context

- Phase 01 required a coverage baseline plus deterministic metadata and smoke input checks.

### Decision, Change, Or Tradeoff

- Added `coverage-baseline.md` as the source-of-truth Phase 01 inventory for current deterministic smoke facts and gaps.
- Fixed stale `skills/bmad-story-automator/workflow.md` frontmatter from `1.12.0` to `1.15.0`.
- Added `npm run version:check` to compare package, plugin, marketplace, module, Python, runtime, and workflow versions.
- Kept `bmad-method@next` as the BMAD installer input for now, but made it explicit through `npm run smoke:input-check` and `.smoke/SMOKE_INPUTS.json` recording during `smoke:prepare`.
- `smoke:prepare` now installs the resolved `bmad-method@<version>` from that manifest instead of resolving the moving dist-tag twice.

### User Impact

- Release metadata drift is now caught before smoke runs.
- Prepared smoke runs still start from the moving BMAD Method npm `next` dist-tag, but each run records the resolved version/integrity and installs that resolved version.
  Phase 02 can decide whether to replace that with a pinned installer version.

## 2026-06-02 - plan creation

### Context

- The deterministic smoke suite currently covers planning/create and two-story dev-loop plumbing.

### Decision, Change, Or Tradeoff

- The plan separates live LLM quality from deterministic control-plane verification. Deterministic gates should prove helper contracts, source-of-truth transitions, state updates, package/install determinism, and mode routing.
- The plan treats automator validate and edit modes as public surfaces that require deterministic coverage, not optional documentation-only flows.

### User Impact

- The next implementation work should not stop at create/dev. It needs to verify review, finalize, retrospective, wrapup, resume, validate, edit, marker, parser, monitor, and packaging behavior.
- `bmad-method@next` and stale workflow version metadata are known risks to resolve early.

## 2026-06-02 - oracle review application

### Context

- Oracle reviewed the deterministic smoke plan and attached critical source paths from the 2026-06-02 bundle.

### Decision, Change, Or Tradeoff

- The plan now treats Phase 02 package/prep identity, Phase 03 helper JSON contracts, and Phase 05 review/finish-loop coverage as release-blocking.
- Default `npm run verify` should target fast local deterministic gates: `test:python`, `version:check`, `pack:assert`, `test:cli`, `smoke:contracts`, `smoke:modes`, and `test:smoke`.
- Prepared-repo reset/network checks should remain explicit through `smoke:prepare`, `smoke:run`, `smoke:dev-loop`, `smoke:finish-loop`, and a wrapper such as `smoke:deterministic-full`.
- Phase 04 should prefer temp BMAD-style fixtures for resume/validate/edit and only use `.smoke/gunz` for realistic external flow coverage.
- Finish-loop commit/finalize needs a hard target-repo safety guard, not only an after-the-fact host HEAD/status sentinel.

### User Impact

- The plan is stricter now: smoke readiness cannot be claimed after only create/dev smokes.
- Implementers should extract shared smoke utilities instead of growing large repeated runners.
- Fixture writes to story files or `sprint-status.yaml` must be described as simulated child workflow output, not automator-owned mutation.
