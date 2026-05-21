# Phase 04 - Agent Complexity And Story Boundaries

## Clean Context Start

Before doing this phase, read [README.md](./README.md), [TODO.md](./TODO.md), [implementation-notes.md](./implementation-notes.md), [handoff-log.md](./handoff-log.md), and prior phase handoff entries. Treat the handoff log as next-agent continuity context. Treat implementation notes as the user-facing record of decisions and tradeoffs.

## Goal

Stop raw agent-plan and complexity JSON from failing late inside command handlers, and strengthen story/epic parse seams without touching tmux/session runtime behavior.

## Inputs

- `skills/bmad-story-automator/src/story_automator/core/diagnostics.py`
- `skills/bmad-story-automator/src/story_automator/commands/orchestrator_epic_agents.py`
- `skills/bmad-story-automator/src/story_automator/core/agent_config.py`
- `skills/bmad-story-automator/src/story_automator/core/epic_parser.py`
- `skills/bmad-story-automator/src/story_automator/core/story_keys.py`
- `skills/bmad-story-automator/src/story_automator/core/sprint.py`
- `tests/test_retro_agent.py`
- `tests/test_runtime_layout.py`

## Implementation Steps

1. Add `skills/bmad-story-automator/src/story_automator/core/agent_plan.py`.
2. Move duplicated agent config/plan behavior from `commands/orchestrator_epic_agents.py` toward core helpers.
3. Implement validators:
   - `validate_complexity_payload(payload) -> list[DiagnosticIssue]`
   - `validate_agents_plan_payload(payload) -> list[DiagnosticIssue]`
   - `load_complexity_payload(path) -> tuple[payload, issues]`
   - `load_agents_plan(path) -> tuple[payload, issues]`
4. Validation rules:
   - root must be an object
   - `stories` must be an array
   - each story needs string `storyId`
   - `complexity.level` normalizes to `low`, `medium`, or `high`
   - task selections cover `create`, `dev`, `auto`, and `review`
   - each task selection has string `primary`
   - `fallback` may be false or string and must normalize like current code
   - unknown fields are allowed unless harmful
5. Keep `StoryKey` and `SprintStatus` mostly unchanged; they are already useful typed seams.
6. Optionally add small dataclasses/helpers in `epic_parser.py` if they preserve current returned JSON shape.
7. Add `tests/test_agent_plan.py` for focused complexity and agents-plan payload coverage. Existing agent config tests may also be extended, but this phase must create the focused module because verification depends on it.

## Verification

```bash
PYTHONPATH=skills/bmad-story-automator/src python3 -m unittest tests.test_retro_agent tests.test_runtime_layout
PYTHONPATH=skills/bmad-story-automator/src python3 -m unittest tests.test_agent_plan
```

## Exit Criteria

- Agent plan and complexity file boundaries fail with field-specific diagnostics.
- Existing fallback normalization and retro override behavior remain unchanged.
- Story/epic parse improvements preserve current CLI JSON shape.
- Tmux/session runtime work is left for Phase 05.

## Implementation Notes Requirements

Keep [implementation-notes.md](./implementation-notes.md) current while implementing. Record module-boundary decisions, any accepted unknown fields, and remaining loose payloads.

## Handoff Requirements

Append a Phase 04 entry to [handoff-log.md](./handoff-log.md) with files changed, tests run, remaining loose payloads, compatibility risks, blockers, and the next recommended command for Phase 05.
