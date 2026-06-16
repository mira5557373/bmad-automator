# Marker File Format

**Location:** Resolved by `orchestrator-helper marker path` for the active runtime layout:
- Claude: `.claude/.story-automator-active`
- Codex: follows the active Codex skill root parent, usually `.agents/.story-automator-active` or `.codex/.story-automator-active`

If a runtime is explicitly selected but the installed story-automator skill is discovered under another supported root, the marker follows that active skill root. Always use `orchestrator-helper marker path` rather than hard-coding the marker path.

**Purpose:** Enables the Stop hook to prevent premature stopping during orchestration.

---

## JSON Structure

```json
{
  "epic": "{epic_id}",
  "currentStory": "{first_story_id}",
  "storiesRemaining": {story_count},
  "stateFile": "{path_to_state_document}",
  "createdAt": "{timestamp}",
  "heartbeat": "{timestamp}",
  "pid": {process_id},
  "projectSlug": "{project_slug}"
}
```

---

## Field Descriptions

| Field | Description |
|-------|-------------|
| `epic` | Epic identifier (e.g., "5") |
| `currentStory` | Current story being processed (e.g., "5.3") |
| `storiesRemaining` | Count of stories left in queue |
| `stateFile` | Path to orchestration state document |
| `createdAt` | Run creation timestamp (ISO 8601), set once at marker create |
| `heartbeat` | Last activity timestamp, refreshed during a run (see below) |
| `pid` | Process ID of orchestrator (crash detection) |
| `projectSlug` | (v2.0) Project identifier for session naming |

---

## Heartbeat Updates

`monitor-session` refreshes the heartbeat on each poll tick while it supervises a story's child session, which keeps the marker fresh through long-running stories. The orchestration loop should also refresh it (`orchestrator-helper marker heartbeat`) at iteration boundaries so the heartbeat never drifts past the staleness window between stories.

**Staleness threshold:** 30 minutes. The stop hook treats a marker whose heartbeat is older than this window as a crashed/abandoned run and releases, so the agent is not blocked forever by a dead orchestrator (see story-automator stop-hook).

---

## Creation Command

```bash
project_slug=$(echo "$("{deriveProjectSlug}" derive-project-slug --project-root "{project-root}")" | jq -r '.slug')
"{stateHelper}" orchestrator-helper marker create --epic "$epic_id" --story "$first_story_id" \
  --remaining "$selected_count" --state-file "$state_path" \
  --project-slug "$project_slug" --pid "$$" --heartbeat "{timestamp}"
```

---

## Related Documentation

- **Stop Hook:** See `stop-hook-config.md` for hook behavior
- **Troubleshooting:** See `stop-hook-troubleshooting.md` for issues
