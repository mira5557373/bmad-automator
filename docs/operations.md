# Operations & Recovery

Incident runbooks for operating a story-automator run. The conceptual docs
([How It Works](./how-it-works.md), [State And Resume](./state-and-resume.md))
explain the model; this page is the "what do I do when X happens" reference.

Resolve the installed helper once (see [CLI Reference](./cli-reference.md) for the
discovery snippet); `$scripts` below refers to it.

## Audit log verification fails

The hash-chained audit log records state mutations. Verify it with:

```bash
"$scripts" audit-verify
# {"ok": true, "valid": true, "last_valid_seq": 42, "path": "..."}
```

- `valid: true` — the chain is intact through `last_valid_seq`.
- `valid: false` — the chain broke at/after `last_valid_seq`. Records **after**
  `last_valid_seq` are suspect (tampering, truncation, or a missing/rotated
  `BMAD_AUDIT_KEY`). Do not trust them. Confirm `BMAD_AUDIT_KEY` matches the key
  the run was started with; if the key is correct and the chain is still broken,
  treat the post-`last_valid_seq` history as compromised and re-derive state from
  the git history and the orchestration-state document rather than the audit log.
- `audit_key_missing` — no `BMAD_AUDIT_KEY` in the environment; export the run's
  key and re-run.

### Rotating the audit key / starting a fresh chain

The audit chain is signed with `BMAD_AUDIT_KEY`; a new key cannot verify a log
written with the old one (that is the point). To rotate the key or start a clean
chain after a confirmed break:

```bash
# 1. Stop the orchestrator (no run should be appending to the log).
# 2. Archive the existing log out of the way.
mv _bmad/audit/audit.jsonl "_bmad/audit/audit-$(date -u +%Y%m%dT%H%M%SZ).jsonl"
# 3. Export a fresh key and re-run; the new chain starts empty.
export BMAD_AUDIT_KEY="$(openssl rand -hex 32)"
```

The archived log stays verifiable with the *old* key (keep it if you need the
history). Full key-lifecycle management is otherwise deferred — see
[SECURITY.md](../SECURITY.md).

## A crashed orchestrator is blocking the agent

If the orchestrator process died but the stop hook keeps blocking, the active
marker's heartbeat will age out. Once it is older than the 30-minute staleness
window the stop hook releases automatically (the agent is allowed to stop). To
recover immediately:

```bash
"$scripts" orchestrator-helper marker check     # inspect the marker / heartbeat
"$scripts" orchestrator-helper marker remove     # clear a confirmed-dead run
```

Only remove the marker after confirming no orchestrator is still running for the
project (a live run refreshes the heartbeat each monitor poll tick).

## A corrupt marker

`marker check` / `marker heartbeat` report `{"error": "marker_corrupt"}` or
`marker_unreadable` when the marker is truncated or not valid JSON (e.g. a crash
mid-write). This is recoverable: remove the marker (`marker remove`) and let the
orchestration loop recreate it. `marker create` refuses to clobber a *live*
run (`run_already_active`) but will overwrite a stale/corrupt one, so a crash
never permanently blocks a re-run.

## A stuck or wedged child session

If a `tmux` session hangs, status probes are bounded (15s) so the monitor poll
loop will not freeze for the full command timeout. Inspect and reclaim:

```bash
"$scripts" tmux-status-check "$session"
"$scripts" tmux-wrapper kill "$session"
```

A duplicate spawn for a session name that already exists is refused
(`session ... already exists`) rather than clobbering the live session's
artifacts.

## A child agent crashed mid-run

Distinct from a *wedged* session (which hangs): the child `claude`/`codex`
process exited (CLI error, OOM, segfault) and its tmux session is gone while the
story is still marked active. Symptoms: the monitor reports the session as
crashed/missing, no tmux session matches the active story, and the heartbeat
stops advancing.

```bash
"$scripts" list-sessions --slug "$slug"          # is the story's session gone?
"$scripts" tmux-status-check "$session"          # crashed / not_found?
tmux capture-pane -t "$session" -p | tail -n 100 # last output (if pane survives)
```

Decide by who is still alive:

- **Orchestrator alive** — let it drive recovery: failure triage classifies the
  crash (`CRASH`) and adaptive retry (M07/M08) re-spawns, up to the retry
  ceiling. No manual action needed.
- **Orchestrator also dead** — clear the stale marker (see *A crashed
  orchestrator is blocking the agent*), then resume from the latest
  orchestration-state document; the crashed story re-runs from its last
  committed action.
- **Unrecoverable** (repeated crash on the same story) — mark the story
  `DEFERRED` in the state document and move on; inspect the captured pane and
  agent CLI logs before retrying.

Run `"$scripts" doctor` first if crashes are immediate on spawn — a missing
agent CLI, exhausted disk, or low file-descriptor limit shows up there.

## Resuming after an interruption

The orchestration-state document (`orchestration-*.md`) is written atomically,
so it is never left half-written even on a crash mid-write. Resume by pointing
the workflow at the latest incomplete state document; see
[State And Resume](./state-and-resume.md).

## Inspecting a run's telemetry

```bash
"$scripts" telemetry-report            # cost/retry/retro rollups
"$scripts" calibration                 # per-(model, task) success rates
"$scripts" drift --baseline a.jsonl --current b.jsonl
```

Every event of one run shares a `run_id` correlation key, so a run's
`StoryStarted → ReviewCycle → StoryCompleted` chain can be joined from the ledger.
