---
name: bmad-story-automator-review
description: 'Runs the autonomous code review flow used by story automator sessions, including auto-fix handling and sprint-status sync. Use when the story automator asks for a non-interactive review of a story.'
---

1. Read `./workflow.yaml`.
2. Then read `./instructions.xml`.
3. Use `./checklist.md` as the validation checklist.
4. Follow the workflow deterministically. If the invocation asks for automatic fixes, apply them without pausing for manual menus.

## Pre-flight: RAMR independence

Before this skill is invoked, the orchestrator MUST route a reviewer
assignment through
`story_automator.core.integration.ramr_review_dispatch.select_reviewer_assignment`.
The helper enforces the M55 anti-bias rule (the review session's
`(cli_id, model)` must differ from the dev-running session's). If RAMR
cannot find a different pair, the helper raises
`ReviewDispatchEscalation` and this skill MUST NOT be spawned — the
operator broadens the CLI registry or signs a PREFERENCE waiver first.
Catching the collision pre-flight saves the wasted spend that an M55
gate-time rejection would otherwise incur.
