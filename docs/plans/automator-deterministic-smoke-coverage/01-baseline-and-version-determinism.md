# Phase 01 - Baseline And Version Determinism

## Clean Context Start

Before doing this phase, read [README.md](./README.md), this phase file, [TODO/phase-01.md](./TODO/phase-01.md), [gate-map.md](./gate-map.md), [implementation-notes.md](./implementation-notes.md), and relevant prior entries in [handoff-log.md](./handoff-log.md).

Do not read later phase files or later TODO files as acceptance criteria for this phase.

## Goal

Create a source-of-truth coverage baseline for the automator workflow and add deterministic version/input checks so later smoke phases are not built on moving or stale package metadata.

## Inputs

- [skills/bmad-story-automator/workflow.md](../../../skills/bmad-story-automator/workflow.md)
- [skills/bmad-story-automator/data/orchestration-policy.json](../../../skills/bmad-story-automator/data/orchestration-policy.json)
- [package.json](../../../package.json)
- [skills/module.yaml](../../../skills/module.yaml)
- [skills/bmad-story-automator/pyproject.toml](../../../skills/bmad-story-automator/pyproject.toml)
- [skills/bmad-story-automator/src/story_automator/__init__.py](../../../skills/bmad-story-automator/src/story_automator/__init__.py)
- [.claude-plugin/plugin.json](../../../.claude-plugin/plugin.json)
- [.claude-plugin/marketplace.json](../../../.claude-plugin/marketplace.json)

## Implementation Steps

1. Build a coverage inventory table that maps each automator mode and policy step to a deterministic gate status: `fact`, `gap`, `blocked`, `stale`, or `spec-only`.
2. Add or update a repo-local deterministic metadata check that asserts version alignment across package, plugin, module, Python package, runtime `__init__`, and workflow frontmatter.
3. Decide whether `bmad-method@next` should be pinned for deterministic prep or recorded/asserted as an explicit smoke input.
4. Update [gate-map.md](./gate-map.md) with the metadata/version gate and any blocked input-pin gate.
5. Record any stale metadata findings in [implementation-notes.md](./implementation-notes.md).

## Verification

- Run the new or updated metadata/version command.
- Run `npm run test:cli`.
- Run `git diff --check`.
- Confirm [gate-map.md](./gate-map.md) has entries for version alignment and smoke input determinism.

## Exit Criteria

- Coverage baseline exists and classifies create, resume, validate, edit, create-story, dev-story, automate, review, commit/finalize, retrospective, wrapup, and package/install surfaces.
- Stale version metadata either fixed or explicitly marked `stale` with a follow-up owner.
- Moving external inputs are pinned or explicitly asserted.
- Phase 01 handoff entry appended.

## Implementation Notes Requirements

Keep [implementation-notes.md](./implementation-notes.md) current while implementing. Record stale metadata, input pinning tradeoffs, and any reason a version surface cannot be aligned immediately.

## Handoff Requirements

Append a Phase 01 entry to [handoff-log.md](./handoff-log.md) with commands run, version surfaces checked, facts classified, blockers, and next recommended command.
