---
name: 'step-03a-execute-review'
description: 'Autonomous execution loop - automate and code review'
nextStep: './step-03b-execute-finish.md'
scriptsDir: '../scripts/story-automator'
outputFile: '{output_folder}/story-automator/orchestration-{epic_id}-{timestamp}.md'
retryStrategy: '../data/retry-fallback-strategy.md'
reviewLoop: '../data/code-review-loop.md'
eventsLedger: '{output_folder}/story-automator/events.jsonl'
workflowJson: '{project-root}/workflow.json'
---

# Step 3a: Execute Review Phase

**Goal:** Run automate (guardrails) and code review loop for the current story.
**Interaction mode:** Deterministic autonomous execution.

---

## Prerequisites

- Step 3 completed (create-story and dev-story done)
- State document updated with current story progress

Set: `scripts="{scriptsDir}"`

---

## Story Loop (Continue from Step 3)

### C. Automate (Guardrails)
*Skip if `overrides.skipAutomate`*

**Apply retry/fallback pattern from `{retryStrategy}`:** Non-blocking, but still retry on failure.

```bash
# --command required (see Spawn Pattern in step-03)
resolve_agent_for_task "auto" "$state_file" "{story_id}"
if should_apply_primary_model "$current_agent"; then
  built_cmd=$("$scripts" tmux-wrapper build-cmd auto {story_id} --agent "$current_agent" --model "$primary_model" --state-file "$state_file")
else
  built_cmd=$("$scripts" tmux-wrapper build-cmd auto {story_id} --agent "$current_agent" --state-file "$state_file")
fi
session=$("$scripts" tmux-wrapper spawn auto {epic} {story_id} \
  --agent "$current_agent" \
  --command "$built_cmd")
result=$("$scripts" monitor-session "$session" --json --agent "$current_agent")
"$scripts" tmux-wrapper kill "$session"
```

- SUCCESS:
  ```bash
  # Update Story Progress: mark automate done
  tmp_state=$(mktemp)
  sed "s/^| ${story_id} |.*$/| ${story_id} | done | done | done | - | - | in-progress |/" "{outputFile}" > "$tmp_state" && mv "$tmp_state" "{outputFile}"
  ```
  Display: `[story {N}/{total}] automate -> done`
  → proceed to D
- FAILURE → retry up to 3 attempts (non-blocking, so fewer retries), then log warning:

  Before each retry attempt, check the retry_start ceiling:

  ```bash
  ceiling=$("$scripts" ceiling-check --gate retry_start \
    --events "{eventsLedger}" --workflow "{workflowJson}")
  verdict=$(echo "$ceiling" | jq -r '.verdict')
  reason=$(echo "$ceiling" | jq -r '.reason')
  bypass=$(echo "$ceiling" | jq -r '.bypass_allowed')
  case "$verdict" in
    BLOCK) echo "❌ retry_start ceiling breached: $reason"
           [ "$bypass" = "true" ] && read -r -p "Bypass? [y/N] " ans
           [ "$ans" = "y" ] || [ "$ans" = "Y" ] || exit 1 ;;
    WARN)  echo "⚠️ retry_start ceiling warning: $reason" ;;
    ALLOW) : ;;
  esac
  ```

  **IF verdict == "BLOCK" and bypass != "true":** stop retrying this story and mark it `skip` per the existing failure path. Surface `$reason` to the operator.
  **IF verdict == "WARN":** surface `$reason` and continue with the retry.
  **IF verdict == "ALLOW":** silent.

  ```bash
  # Update Story Progress: mark automate skipped
  tmp_state=$(mktemp)
  sed "s/^| ${story_id} |.*$/| ${story_id} | done | done | skip | - | - | in-progress |/" "{outputFile}" > "$tmp_state" && mv "$tmp_state" "{outputFile}"
  ```
  Display: `[story {N}/{total}] automate -> skip (non-blocking)`
  → proceed to D

### D. Code Review Loop

**Review preflight:** Before this section runs, execute the spec-compliance gate at [`skills/bmad-story-automator/steps-c/step-03ab-spec-compliance.md`](./step-03ab-spec-compliance.md) and proceed only if the chain's `decision` literal is `pass` or `warn` (M06b REQ-06, REQ-10).

**See `{reviewLoop}` for complete script-based review cycle with v2.3 per-task agent configuration.**

**MANDATORY log-summary contract (every review cycle):**
- Run a single grep/regex pass over review output first.
- Return only compact fields to parent flow: `next_action`, `confidence`, `error_class`, `issues_count`, `top_issues`.
- Do not carry full log payloads forward unless escalation requires raw evidence.

```bash
review_log=$(echo "$result" | jq -r '.output_file')
review_focus=$(grep -nE "SUCCESS|FAIL|ERROR|CRITICAL|WARN|RETRY|ESCALATE|ISSUE" "$review_log" | head -n 120)
if [ -z "$review_focus" ]; then
  review_focus=$(tail -n 120 "$review_log")
fi

# Compact subprocess-style summary contract for parent flow
review_summary=$("$scripts" orchestrator-helper parse-output "$review_log" review --state-file "$state_file" | jq -c '
  {
    next_action: (.next_action // "retry"),
    confidence: (.confidence // 0),
    error_class: (.error_class // "unknown"),
    issues_count: ((.issues // []) | length),
    top_issues: ((.issues // [])[:3])
  }
')
```

Key points:
- Up to 5 cycles using `story-automator tmux-wrapper spawn review` + `story-automator monitor-session`
- **Agent:** Uses per-task config from state document (`resolve_agent_for_task "review"`)
- **Verification:** Uses `--workflow review --story-key` for sprint-status verification
- **States:** `completed` (verified):
  ```bash
  # Update Story Progress: mark code-review done
  tmp_state=$(mktemp)
  sed "s/^| ${story_id} |.*$/| ${story_id} | done | done | done | done | - | in-progress |/" "{outputFile}" > "$tmp_state" && mv "$tmp_state" "{outputFile}"
  ```
  Display: `[story {N}/{total}] review -> done`
  → E | `incomplete` → count as failed attempt, retry until maxCycles, then CRITICAL escalate (Trigger #8)
- Exit loop when sprint-status shows "done"
- If `review_summary.next_action` is ambiguous, ask one clarifying question before escalating.

---

## Auto-Proceed to Finalization

Display: "**Code review complete. Proceeding to finalize commits and status checks...**"

```bash
"$scripts" orchestrator-helper state-update "{outputFile}" \
  --set currentStep=step-03b-execute-finish \
  --set lastUpdated="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
echo "- **[$(date -u +%Y-%m-%dT%H:%M:%SZ)]** Code review complete, proceeding to finalization" >> "{outputFile}"
```

---

## Then
→ Immediately load and execute `{nextStep}`
