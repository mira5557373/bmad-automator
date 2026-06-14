# M01 — Site Inventory

**Date:** 2026-06-14
**Scope:** M01 event-types wedge atom

## Pre-existing collisions check

Grep run: `grep -rn "telemetry_events\|EVENT_TYPE\|_REGISTRY\|class Event" skills/bmad-story-automator/src/ tests/`

Result: zero matches in `skills/bmad-story-automator/src/`. No existing module would collide with `core/telemetry_events.py`. No existing `EVENT_TYPE` discriminator pattern, no `_REGISTRY` pattern, no `class Event` declarations.

## Files M01 will create (no existing equivalent)

1. `skills/bmad-story-automator/src/story_automator/core/telemetry_events.py`
2. `tests/test_telemetry_events.py`

## Files M01 will modify

None. M01 is purely additive. M02 will wire emission into existing log sites.

## Files M02+ will need to modify (out of scope for M01, documented here for traceability)

- `skills/bmad-story-automator/src/story_automator/commands/orchestrator.py` (wire emit)
- `skills/bmad-story-automator/src/story_automator/commands/orchestrator_epic_agents.py` (wire emit for retro)
- `skills/bmad-story-automator/src/story_automator/core/tmux_runtime.py` (wire emit for tmux events)

These are NOT touched by M01.
