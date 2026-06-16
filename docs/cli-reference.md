# CLI Reference

The installed helper command is under each installed skill root:

```text
<installed-skill-root>/bmad-story-automator/scripts/story-automator
```

It exposes one flat command surface with grouped responsibilities.

## Command Families

```mermaid
flowchart TD
    A["story-automator"] --> B["Parsing"]
    A --> C["State"]
    A --> D["tmux"]
    A --> E["Orchestrator helpers"]
    A --> F["Agent config"]
    A --> G["Basic utilities"]
    A --> H["Verification, Budget & Telemetry"]
```

## Parsing Commands

- `parse-epic --file <path>`
- `parse-story --epic <path> --story <id> --rules <file>`
- `parse-story-range --input <selection> --total <count> --ids <csv>`
- `epic-complete --epic <path> --range <csv>`

Use these during preflight to keep story selection and complexity scoring deterministic.

## State Commands

- `build-state-doc`
- `state-metrics --state <file>`
- `validate-state --state <file>`
- `sprint-compare --state <file> --sprint <file>`

Use these to create, inspect, and validate orchestration state.

## tmux Commands

- `tmux-wrapper spawn`
- `tmux-wrapper build-cmd`
- `tmux-wrapper kill`
- `tmux-wrapper list`
- `monitor-session`
- `tmux-status-check`
- `codex-status-check`
- `heartbeat-check`

Critical rule:

- always pass `--command` to `tmux-wrapper spawn`

## Orchestrator Helper Commands

- `orchestrator-helper sprint-status get|exists|check-epic`
- `orchestrator-helper parse-output`
- `orchestrator-helper state-list`
- `orchestrator-helper state-latest`
- `orchestrator-helper state-latest-incomplete`
- `orchestrator-helper state-summary`
- `orchestrator-helper state-update`
- `orchestrator-helper marker create|remove|check|heartbeat`
- `orchestrator-helper normalize-key`
- `orchestrator-helper story-file-status`
- `orchestrator-helper verify-step`
- `orchestrator-helper verify-code-review`
- `orchestrator-helper get-epic-stories`
- `orchestrator-helper check-epic-complete`
- `orchestrator-helper check-blocking`
- `orchestrator-helper agents-build`
- `orchestrator-helper agents-resolve`
- `orchestrator-helper escalate session-crash <context>`
- `orchestrator-helper commit-ready <story-key>`
- `orchestrator-helper retro-agent`

These commands are the orchestration control plane. `escalate`, `commit-ready`,
`marker create`, `verify-code-review`, `check-blocking`, `agents-resolve`, and
`retro-agent` also emit M01/M02 telemetry events carrying the per-run `run_id`
correlation key derived from the active marker.

## Agent Config Commands

- `agent-config list`
- `agent-config save`
- `agent-config load`
- `agent-config delete`

These support saved presets and generated agent plans.

## Verification, Budget & Telemetry Commands

These commands wire the runtime's safety, verification, and telemetry building
blocks onto the flat CLI surface. Each prints a single compact JSON object to
stdout (so BMAD step markdown can branch via `jq`) and is read-only with respect
to source state unless noted.

- `ceiling-check --gate <init|story_start|retry_start> [--events <jsonl>]` —
  evaluates the M03 budget ceilings and prints an `ALLOW` / `WARN` / `BLOCK`
  verdict. Read-only: never writes the ledger, never prompts.
- `trust_verify --diff <path> --gaps <path> --spec <path>` — chains the three
  M06a trust-but-verify layers (gap validation, spec compliance, feature
  testing), derives a single `pass` / `warn` / `block` decision, and writes the
  five-key result to `.claude/trust-verify-output/result.json`. Exit code:
  `0` on pass/warn, `2` on block (so the step can halt), `1` on input error.
- `telemetry-report [--events <jsonl>] [--epic <id>] [--report <kind>]` —
  aggregates the M02 telemetry stream into rollups (cost-by-epic,
  retry-attempts-by-story, per-epic retro inputs).
- `calibration [--events <jsonl>] [--model <id>] [--task <kind>] [--report]` —
  prints the M08 per-`(model_id, task_kind)` success-rate table. A missing
  ledger is not an error (empty table, `ok:true`).
- `drift --baseline <jsonl> --current <jsonl> [--format json|text]` — computes
  the M09 drift report between two calibration snapshots.
- `triage [--json <event>]` — classifies a single telemetry event (read from
  `--json` or stdin) into an M07 failure-triage verdict
  (`failure_class` / `confidence`).
- `audit-verify [--project-root <path>]` — verifies the M04 hash-chained audit
  log and prints `valid` + `last_valid_seq`. The audit key is loaded from the
  environment and never echoed.
- `record-cost --epic <id> --model <id> --cost-usd <n> [--tokens-in <n>] [--tokens-out <n>] [--story-key <key>] [--phase <name>] [--run-id <id>] [--now <iso>]` —
  the cost ingestion primitive: appends one `CostCharged` row to
  `telemetry/events.jsonl` so `ceiling-check` and `telemetry-report` reflect
  real spend (closes the inert-ceiling gap).

Note: `trust_verify` is registered with an underscore (per the bundled skill
contract); the other commands use hyphens.

## Basic Utility Commands

- `derive-project-slug`
- `ensure-marker-gitignore`
- `ensure-stop-hook`
- `stop-hook`
- `list-sessions`
- `commit-story`
- `validate-story-creation` (legacy compatibility wrapper; prefer `orchestrator-helper verify-step create`)

## Typical Patterns

Start by resolving the installed helper from the supported skill roots:

```bash
scripts=""
for root in .agents/skills .claude/skills .codex/skills; do
  candidate="$root/bmad-story-automator/scripts/story-automator"
  if [ -x "$candidate" ]; then
    scripts="$candidate"
    break
  fi
done
[ -n "$scripts" ] || { echo "story-automator not found in supported skill roots" >&2; exit 1; }
```

### Build And Spawn

```bash
cmd="$("$scripts" tmux-wrapper build-cmd review 1.2 --agent claude)"
session="$("$scripts" tmux-wrapper spawn review 1 1.2 --agent claude --command "$cmd")"
```

### Monitor With Review Verification

```bash
"$scripts" monitor-session "$session" --json --agent claude --workflow review --story-key 1.2
```

### Resolve Agent For A Story Task

```bash
"$scripts" orchestrator-helper agents-resolve --state-file "$state_file" --story 1.2 --task review
```

### Verify Create Success

```bash
"$scripts" orchestrator-helper verify-step create 1.2 --state-file "$state_file"
```

Legacy compatibility:

```bash
"$scripts" validate-story-creation check 1.2 --state-file "$state_file"
```

## Read Next

- [Agents And Monitoring](./agents-and-monitoring.md)
- [Troubleshooting](./troubleshooting.md)
