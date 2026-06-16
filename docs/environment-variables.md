# Environment Variables

This documents every environment variable the `story_automator` Python runtime
reads. It is the single reference for the knobs available when driving the
automator from a shell, a stop-hook, or a parent orchestrator session.

> Scope: this is the mainline (`bmad-story-automator`) runtime. Ported milestone
> modules (telemetry/audit/budget/etc.) live on feature branches and add their
> own variables (`BMAD_AUDIT_KEY`, budget/ceiling knobs, …); those are
> documented with their respective modules, not here.

## Operator configuration

| Variable | Purpose | Default |
| --- | --- | --- |
| `PROJECT_ROOT` | Project root the runtime operates on. Relative/empty values resolve against the current working directory. | current working directory |
| `BMAD_SKILLS_ROOT` | Explicit skills-root override. Highest precedence in skill resolution; may point at the skills dir or directly at the `bmad-story-automator` skill. | auto-detected (`.claude`/`.agents`/`.codex` skills trees, then bundled) |
| `BMAD_RUNTIME_PROVIDER` | Forces the runtime provider (`claude` or `codex`), which controls hook/config syntax. | inferred from the installed skill layout |
| `STORY_AUTOMATOR_RUNTIME_PROVIDER` | Alias for `BMAD_RUNTIME_PROVIDER`. | — |
| `BMAD_STORY_AUTOMATOR_ACTIVE_MARKER` | Overrides the active-run marker file path. Relative paths resolve against `PROJECT_ROOT`. | provider-specific path under the project |
| `STORY_AUTOMATOR_ACTIVE_MARKER` | Alias for `BMAD_STORY_AUTOMATOR_ACTIVE_MARKER` (lower precedence). | — |
| `STORY_AUTOMATOR_STATE_FILE` | Points the runtime at a run state file. Resolution order: explicit `--state-file` argument → `STORY_AUTOMATOR_STATE_FILE` → active-run marker. | none |
| `SA_TMUX_RUNTIME` | tmux runtime mode. `auto` selects the schema-v1 runner; `legacy` forces the older send-keys path. | `auto` |
| `AI_AGENT` | Agent type for spawned child sessions (`claude` or `codex`). | runtime provider |
| `AI_COMMAND` | Explicit AI command string for child sessions. When set and `AI_AGENT` is unset, the agent is inferred from this command. | derived from `AI_AGENT` |
| `MAX_REVIEW_CYCLES` | Legacy override for `workflow.repeat.review.maxCycles` in policy. | policy value |
| `MAX_CRASH_RETRIES` | Legacy override for `workflow.crash.maxRetries` in policy. | policy value |
| `SHELL` | Preferred shell for tmux sessions (falls back through tmux's default-shell, then `/bin/sh`). | tmux default / `/bin/sh` |

## Internal runtime plumbing (do not set manually)

These are set and consumed by the runtime itself — by spawned child sessions and
the generated stop-hook/runner scripts — and are not operator configuration:

- `STORY_AUTOMATOR_CHILD` — marks a process as a spawned child so the stop-hook does not recurse.
- `CLAUDECODE` — cleared in child command strings to detach from a parent Claude Code session.
- `STATE_FILE`, `STATE_LIFECYCLE`, `STATE_RESULT`, `STATE_FAILURE_REASON`, `STATE_RUNNER_PID`, `STATE_CHILD_PID`, `STATE_EXIT_CODE`, `STATE_STARTED_AT`, `STATE_FINISHED_AT` — the runner→state-recorder protocol passed between the generated bash runner script and its embedded Python state call.
