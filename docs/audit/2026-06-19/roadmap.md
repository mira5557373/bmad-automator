# bmad-automator Production-Readiness Audit (LITE) — Phased Roadmap

Phase rules (LITE prompt §"Output format"):
- **P0** (ship-blockers) = every `severity:must AND likelihood:high`
- **P1** (next release) = every `severity:must AND likelihood:medium` + every `severity:should AND likelihood:high`
- **P2** (backlog) = everything else (must:low, should:medium, should:low, nice:*)

Effort calibration: `S` ≤ 1 h, `M` ≤ 4 h, `L` ≤ 2 d (~16 h), `XL` > 2 d.

---

## P0 — Ship-blockers (14 findings, ~62 h)

The trip-wire-shaped findings cluster in D6 (8 of 14 if including D6 must:medium); the tool-call-boundary gap clusters in D7. Recommend tackling D6 + D7 as a single hardening sprint with a shared `TripwireEvent` + `AgentInvoked` plumbing pass.

### D1 — Correctness (2 findings, 5 h)
- **F-001** `M` — Calibration table permanently empty — events lack model_id/task_kind
- **F-002** `S` — parse_event raises TypeError on forward-compat events with extra fields

### D3 — Subprocess hygiene (1 finding, 1 h)
- **F-003** `S` — BMAD_AUDIT_KEY leaks to every child via /proc/<pid>/environ

### D6 — Prompt-injection tripwires (5 findings, 26 h)
- **F-004** `L` — Tripwire infrastructure (signatures + base event + scanner hook) absent
- **F-005** `S` — StoryInjectionSuspected — canonical jailbreak phrases unmonitored
- **F-006** `M` — ToolCallInStoryDetected — fenced tool_call / JSON shape unmonitored
- **F-007** `M` — UnicodeAnomalyInStory — RTL/zero-width/tag chars/homoglyphs unmonitored
- **F-008** `S` — RoleMarkerInjection — system:/user:/assistant: line starts unmonitored

### D7 — Child-agent tool-call boundary (3 findings, 24 h)
- **F-009** `M` — Spawning an LLM child is not recorded in the hash-chained audit log
- **F-010** `M` — No per-persona tool allowlist for Claude — reviewer has full file-write
- **F-011** `L` — Claude child is not sandboxed to the project root (Codex is)

### D9 — Python matrix + declared deps (1 finding, 1 h)
- **F-012** `S` — filelock and psutil imported but undeclared in pyproject

### D10 — Operability (2 findings, 5 h)
- **F-013** `M` — No `story-automator doctor` command — operator has no preflight
- **F-014** `S` — Runbook missing for 'child agent crashed mid-run'

**P0 totals:** 6 × S + 6 × M + 2 × L = 6 + 24 + 32 = **~62 h**

---

## P1 — Next release (17 findings, ~29 h)

Mostly drop-in defensive parsing tightening + a coverage and Python-floor pass. Two-thirds are S-effort.

### D1 — Correctness (3 findings, 3 h)
- **F-015** `S` — is_stale() crashes on ISO timestamp with +00:00 offset
- **F-016** `S` — failure_triage classifier reads nonexistent 'trigger' attr, misses POLICY
- **F-027** `S` — TelemetryReader.iter_events aborts whole stream on first malformed JSONL *(downgraded from P0 by skeptic — see index.md)*

### D2 — Defensive parsing (3 findings, 3 h)
- **F-017** `S` — parse_agent_config_json crashes (AttributeError) on non-dict complexityOverrides
- **F-018** `S` — _matches_schema accepts unbounded LLM strings (DoS / log poisoning)
- **F-019** `S` — spec_compliance accepts unbounded evidence/req_id from claude -p stdout

### D4 — /proc + tmux (1 finding, 1 h)
- **F-020** `S` — BMAD_AUDIT_KEY persists in os.environ for orchestrator lifetime

### D6 — Prompt-injection tripwires (4 findings, 7 h)
- **F-021** `S` — EnvVarReferenceInStory — $ENV / ${ENV} / %ENV% / $env:ENV unmonitored
- **F-022** `M` — OperatorOverrideKeywordObserved — override JSON keys unmonitored
- **F-023** `S` — Base64BlobInStory — contiguous [A-Za-z0-9+/=] ≥256 chars unmonitored
- **F-024** `S` — AltTextOrLinkAnomaly — javascript:/data:/file: URI unmonitored

### D8 — Coverage + Hypothesis (4 findings, 13 h)
- **F-028** `S` — commands/agent_config_cmd.py at 8% line coverage (floor 75%, −67 pp)
- **F-029** `M` — commands/basic.py at 45% line coverage (floor 75%, −30 pp)
- **F-030** `M` — No hypothesis state-machine test for core/atomic_io (integrity-critical)
- **F-031** `M` — No hypothesis state-machine test for core/audit append+verify

### D9 — Python matrix (1 finding, 1 h)
- **F-032** `S` — 9 dataclass tests fail on declared min Python 3.11 — CI signal poisoned

### D10 — Operability (1 finding, 1 h)
- **F-025** `S` — Audit-chain runbook lacks key-rotation procedure + forensics steps

**P1 totals:** 13 × S + 4 × M = 13 + 16 = **~29 h**

---

## P2 — Backlog (40 findings, ~90 h)

Cleanup and hardening. Coverage gaps (D8) and defense-in-depth (D2, D4) dominate.

### D1 — Correctness (8 findings, 11 h)
- **F-033** `S` — _classify_story_failed substring-matches 'parse' too broadly
- **F-034** `S` — update_simple_frontmatter rewrites body lines matching key prefix
- **F-035** `M` — load_session_state silently returns {} on corrupted JSON
- **F-036** `S` — _claude_completion_marker_present false-positive on 'tested for 3m' text
- **F-037** `S` — extract_last_action uses fragile +2 offset; misses 'last' action
- **F-053** `S` — filter_input_box silently swallows lines starting with '|' (markdown table rows)
- **F-054** `S` — extract_json_block fails on JSON with trailing prose or nested objects
- **F-063** `S` — _classify_story_deferred reads nonexistent attempt_count attribute

### D2 — Defensive parsing (7 findings, 10 h)
- **F-038** `S` — gap_validator.parse_gap_list accepts 5+ MB description/symbol strings
- **F-039** `S` — state.py / agent_config_cmd.py / orchestrator_parse skip top-level dict check
- **F-055** `S` — spec_compliance / orchestrator_parse silently last-wins on duplicate JSON keys
- **F-056** `S` — _has_required_keys accepts prototype-pollution-shaped keys
- **F-057** `S` — _matches_schema unbounded recursion (stack DoS at depth ~1k)
- **F-064** `M` — telemetry_events dataclass fields not runtime-typechecked
- **F-065** `S` — extract_json_line scans 100MB single lines with re.findall (CPU DoS)

### D3 — Subprocess hygiene (4 findings, 7 h)
- **F-040** `S` — LLM parser prompt embedded in argv, leaking via /proc/<pid>/cmdline
- **F-058** `S` — Two near-duplicate run_cmd helpers risk drift on security hardening
- **F-066** `M` — claude/codex/tmux/git rely on PATH lookup — doctor should pin paths
- **F-067** `S` — run_cmd inherits LANG/LC_* uncontrolled — parsing of child output may vary

### D4 — /proc + tmux (5 findings, 8 h)
- **F-041** `S` — tmux server inherits BMAD_AUDIT_KEY — pane-env scrub is incomplete
- **F-059** `S` — Legacy spawn path does not scrub BASH_ENV (runner path does)
- **F-060** `S` — tmux send-keys without -l interprets key-binding tokens in command string
- **F-068** `S` — AI_COMMAND env var forwarded to child build with no sanitization
- **F-069** `M` — tmux pane inherits unfiltered LD_PRELOAD / LD_LIBRARY_PATH / PYTHONSTARTUP

### D5 — Shell-script injection (2 findings, 2 h)
- **F-061** `S` — Unquoted RHS of ${var#prefix} treats TARGET_ROOT as glob pattern
- **F-070** `S` — SC2155 — local+command-substitution masks date(1) exit status

### D6 — Prompt-injection tripwires (1 finding, 4 h)
- **F-042** `M` — No StoryFileMutatedMidAttempt sha-pinning for tripwire window

### D7 — Child-agent tool-call boundary (3 findings, 6 h)
- **F-043** `S` — claude -p spec-compliance child inherits full parent env and no audit
- **F-044** `M` — No DisallowedToolCallObserved event — boundary trips are invisible
- **F-062** `S` — The composed child prompt is not hashed into telemetry

### D8 — Coverage + Hypothesis (6 findings, 33 h)
- **F-045** `M` — core/common.py at 58% line / 50% branch (floor 80%/75%, −22 pp)
- **F-046** `L` — core/tmux_runtime.py at 62% line / 57% branch (floor 80%/75%, −18 pp)
- **F-047** `M` — commands/tmux.py at 62% line / 59% branch (floor 75%/70%, −13 pp)
- **F-048** `M` — commands/orchestrator.py at 65% line / 62% branch (floor 75%/70%, −10 pp)
- **F-049** `S` — No hypothesis round-trip for telemetry_events.parse_event on adversarial text
- **F-050** `M` — No hypothesis adversarial-input strategy for frontmatter / epic_parser

### D9 — Python matrix (2 findings, 2 h)
- **F-051** `S` — README/classifiers/pyproject agree on >=3.11 but reality runs only on >=3.12
- **F-071** `S` — Python 3.14 is undeclared in classifiers but runs; document or claim it

### D10 — Operability (2 findings, 2 h)
- **F-026** `S` — Error-code catalog is partial — actual codes outnumber documented ~3:1 *(must:low — only here because P2 captures all must:low under the LITE rubric)*
- **F-052** `S` — No `telemetry tail` / recent-events view for live debugging

**P2 totals:** 26 × S + 12 × M + 1 × L = 26 + 48 + 16 = **~90 h**

---

## Cross-phase totals

| Phase | rows | S | M | L | XL | est. wall-clock |
|---|---|---|---|---|---|---|
| **P0** | 14 | 6 | 6 | 2 | 0 | ~62 h |
| **P1** | 17 | 13 | 4 | 0 | 0 | ~29 h |
| **P2** | 40 | 26 | 12 | 1 | 0 | ~90 h |
| **All** | **71** | **45** | **22** | **3** | **0** | **~181 h** |

## Sequencing recommendation

1. **Sprint 1 (P0 D6 + D7)** — land `TripwireEvent` base + `AgentInvoked` audit event together; they share telemetry plumbing and unblock 8 of the 14 P0 rows (~50 h).
2. **Sprint 2 (P0 D1/D3/D9/D10 + P1 D9 + D10)** — small/medium fixes plus the `doctor` command; closes the P0 long tail and the most-visible P1 docs/runbook gaps (~13 h + 3 h).
3. **Sprint 3 (P1 D1/D2/D4 + remaining P1 D6/D8)** — defensive-parsing pass + hypothesis state machines (~26 h).
4. **Backlog (P2)** — pull on demand, prioritising the D8 coverage block when CI signals regress.

## Notes on scope

- `must:low` finding F-026 (error-code catalog) lands in P2 by the LITE phase rules but is documentation-only and worth bundling with F-025 in Sprint 2 if a docs operator is available.
- F-027 was originally `must:high` (F-D1-002 in dimension findings) and was downgraded by skeptic verification (`/tmp/audit-lite/skeptics/F-D1-002.md`) — reason: the loud-not-silent behaviour is documented contract (REQ-07) and the only end-user consumer already wraps the iterator in try/except. Treat the SHOULD as a forward-resilience improvement, not a regression.
