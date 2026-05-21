# Phase 06 - E2E Docs And Release Readiness

## Clean Context Start

Before doing this phase, read [README.md](./README.md), [TODO.md](./TODO.md), [implementation-notes.md](./implementation-notes.md), [handoff-log.md](./handoff-log.md), and prior phase handoff entries. Treat the handoff log as next-agent continuity context. Treat implementation notes as the user-facing record of decisions and tradeoffs.

## Goal

Prove the observability and validation work end-to-end, update operator-facing docs, and prepare the issue branch for review.

## Inputs

- `scripts/smoke-test.sh`
- `docs/development.md`
- `docs/state-and-resume.md`
- `docs/troubleshooting.md`
- `docs/how-it-works.md`
- `skills/bmad-story-automator/data/crash-recovery.md`
- `skills/bmad-story-automator/data/orchestrator-rules.md`
- All tests touched in earlier phases

## Implementation Steps

1. Add `tests/test_diagnostics_e2e.py` or equivalent E2E-lite tests for representative failure paths:
   - malformed LLM output
   - invalid state frontmatter
   - illegal state transition
   - malformed agent plan
   - missing or stale runtime/session state where feasible
2. Update docs to describe structured diagnostics and recovery hints.
3. Verify the docs examples match actual JSON output.
4. Run focused tests from each phase.
5. Run the repo's broad verification command.
6. Review `git diff --stat` and file sizes. Split any file approaching the repo's LOC guidance.

## Verification

```bash
PYTHONPATH=skills/bmad-story-automator/src python3 -m unittest discover -s tests
npm run test:cli
npm run pack:dry-run
npm run test:smoke
npm run verify
git diff --stat
```

If any command is unavailable or requires external runtime setup, record the exact blocker and the closest completed verification.

## Exit Criteria

- Representative malformed inputs fail early with actionable diagnostics.
- Key orchestration stages emit stable structured diagnostics or events.
- Docs and validation output agree.
- Existing successful automator workflows continue to pass local verification.
- Branch is ready for review or remaining blockers are explicit.

## Implementation Notes Requirements

Record test coverage decisions, any known gaps in E2E feasibility, docs changes, and remaining risks.

## Handoff Requirements

Append a Phase 06 entry to [handoff-log.md](./handoff-log.md) with final commands, results, unresolved risks, files changed, and recommended PR summary.
