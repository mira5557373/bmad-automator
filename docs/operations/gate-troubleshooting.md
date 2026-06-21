# Gate Troubleshooting Runbook

Operator guide for the production-readiness gate (M10).

## 1. First-Run Profile Discovery

Verify the effective profile:

```bash
story-automator doctor
```

Profile precedence (highest wins):

1. `_bmad/bmm/story-automator.policy.json` override
2. Project-local `data/profiles/<name>.json`
3. Bundled `data/profiles/default.json`

If profile is malformed:

```bash
# Inspect raw profile
jq . _bmad/bmm/story-automator.policy.json

# Validate shape
PYTHONPATH=skills/bmad-story-automator/src python3 -c \
  "from story_automator.core.product_profile import load_effective_profile; \
   p = load_effective_profile('.'); print(p['id'])"
```

## 2. Verdict Interpretation Decision Tree

| Overall   | Meaning                          | Next Action                      |
|-----------|----------------------------------|----------------------------------|
| PASS      | All categories met thresholds    | Commit; move to next story       |
| CONCERNS  | Thresholds met with caveats      | Commit; mitigation debt recorded |
| FAIL      | One or more categories failed    | Remediate or park                |
| WAIVED    | Operator waiver in effect        | Commit; waiver audit trail kept  |

Per-category verdicts (in `gate_file.categories.<name>.verdict`):

- `PASS` — coverage met required threshold
- `CONCERNS` — below ideal, above minimum
- `FAIL` — below minimum or error/timeout (fail-closed)
- `NA` — category disabled via `profile.categories_na`

```bash
# Inspect category verdicts
jq '.categories | to_entries[] | {(.key): .value.verdict}' \
  _bmad/gate/verdicts/<gate_id>.json
```

## 3. PARK + Remediation Exhaustion Flow

When `review_max_cycles` (default: 5) is exhausted, the story is parked:

```bash
# Check parked stories
orchestrator-helper gate status

# Filter by reason
orchestrator-helper gate status --state=exhausted
orchestrator-helper gate status --state=risk-9

# Resume a parked story for re-evaluation
orchestrator-helper gate resume <gate_id>
```

After resuming, invalidate the old gate to force re-evaluation:

```bash
orchestrator-helper gate invalidate <story_id>
```

## 4. Partial-FAIL Playbook

When only specific categories fail:

```bash
# Identify failing categories
jq '.categories | to_entries[] | select(.value.verdict == "FAIL") | .key' \
  _bmad/gate/verdicts/<gate_id>.json

# Check evidence for a specific category
ls _bmad/gate/evidence/<gate_id>/
jq '.status, .findings' _bmad/gate/evidence/<gate_id>/<collector>-*.json
```

Options:
- Fix the specific issue and re-run (invalidate gate first)
- Disable the category via `profile.categories_na` if not applicable
- Request a waiver (see section 6)

## 5. Profile-Drift Re-Gate Procedure

When profile or factory version changes, existing gates are stale:

```bash
# Invalidate all gates for a story
orchestrator-helper gate invalidate <story_id>

# Invalidate all gates for an epic
orchestrator-helper gate invalidate <epic_id>

# Verify invalidation
ls _bmad/gate/verdicts/*.invalidated.json
```

The next gate run will re-evaluate from scratch with the new profile.

Drift is detected automatically via `GateProfileDriftAudit` in the audit log:

```bash
# Check audit log for drift events
grep GateProfileDrift _bmad/audit/*.jsonl | jq .
```

## 6. Waiver SOP

Waivers require:
- `waiver_id` — unique identifier
- `operator_id` — who issued it
- `issued_at` / `expires_at` — ISO timestamps (max TTL: 30 days)
- `failing_categories` — which categories are waived
- `reason` — human-readable justification
- `profile_hash` — locks waiver to a specific profile version
- `signature` — HMAC signature for tamper detection

```bash
# Check waiver validity
jq '.waivers[]' _bmad/gate/verdicts/<gate_id>.json

# Verify waiver hasn't expired
jq '.waivers[] | select(.expires_at < now | todate)' \
  _bmad/gate/verdicts/<gate_id>.json
```

Audit trail: all waivers are recorded in the gate file and audit log.

## 7. Atomic-Gate Crash Recovery

The gate uses a `gate-in-progress.json` marker for crash detection:

```bash
# Check for stale marker
cat _bmad/gate/gate-in-progress.json 2>/dev/null && echo "STALE MARKER" || echo "clean"

# Manual recovery (normally automatic on next run)
orchestrator-helper gate status
```

Automatic recovery on next run:
1. Reads marker
2. If no verdict exists, deletes orphan evidence
3. Clears marker
4. Re-runs gate from scratch (fail-closed)

Manual clear (last resort):

```bash
rm _bmad/gate/gate-in-progress.json
# Optionally clean orphan evidence
rm -rf _bmad/gate/evidence/<gate_id>/
```

## 8. Operator Takeover Checklist

To pause and manually intervene:

1. Note the current gate status: `orchestrator-helper gate status`
2. If in-progress, wait for completion or clear the marker (section 7)
3. Edit gate artifacts as needed
4. Invalidate the gate: `orchestrator-helper gate invalidate <story_id>`
5. Resume: `orchestrator-helper gate resume <gate_id>` (if parked)
6. Re-run the gate evaluation

## 9. Repeated-Timeout Handling

If a collector repeatedly times out:

```bash
# Check evidence for timeouts
jq 'select(.status == "timeout")' _bmad/gate/evidence/<gate_id>/*.json

# Option A: raise the timeout
# In profile or policy override:
# "timeouts": { "<category>": <seconds> }

# Option B: kill-switch the collector
# In profile:
# "rules": { "<category>": { "disabled_tools": ["<tool_name>"] } }
```

Timeouts are fail-closed: they count as errors, not passes.
