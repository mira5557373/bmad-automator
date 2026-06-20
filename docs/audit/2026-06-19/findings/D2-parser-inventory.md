# D2 — Parser inventory (LLM-output ingestion + JSON load sites)

Trust model: subprocess stdout (`claude`/`codex` runtime) is UNTRUSTED. Asset files written by trusted tooling (state file, presets, agents.md, complexity.json) are TRUSTED-on-disk but defended fail-closed because a buggy LLM child may have written them.

| # | file:line | input_source | what_it_parses | brief_notes |
|---|---|---|---|---|
| 1 | core/spec_compliance.py:163 (`_parse_envelope`) | subprocess_stdout | `claude -p` JSON envelope `{verdicts:[…], model_invocation_ms}` | Layer-2 trust-but-verify. Strong type guards; **no length caps**, control chars accepted in evidence/req_id, dup-keys silent. |
| 2 | core/gap_validator.py:120 (`parse_gap_list`) | subprocess_stdout | `{gaps:[{file_path,line,symbol,description,severity}]}` | Strong key/severity/type checks; **no length cap** on `description`/`symbol`. |
| 3 | commands/orchestrator_parse.py:62 (`parse_output_action`) | subprocess_stdout | model parse-output JSON line | Schema is structurally checked but `_matches_schema` accepts **arbitrarily large strings**, control chars, recursion-depth attacks. |
| 4 | commands/orchestrator_parse.py:78 (`_load_parse_contract`) | asset_file (parse schema) | schema sidecar (`schemaPath`) | Trusted local file; checks types of `requiredKeys`/`schema`. |
| 5 | core/agent_config.py:50 (`parse_agent_config_json`) | json_field/CLI string | resolved agent-config object | **AttributeError** crash on non-dict `complexityOverrides` (e.g. JSON array). State-changing path: drives agent dispatch. |
| 6 | core/agent_config.py:38 (`load_presets_file`) | asset_file | presets.json | Crashes on non-dict top level (no isinstance guard around setdefault). |
| 7 | core/agent_config.py:195 (`build_agents_file`) | asset_file | complexity.md JSON | Crashes (`.get` on non-dict). |
| 8 | core/agent_config.py:239 (`resolve_agents`) | asset_file (agents.md) | embedded JSON inside ```json fence | json.loads on extracted block; passes through to dispatch w/o length cap. |
| 9 | commands/orchestrator_epic_agents.py:332 | asset_file | complexity.md JSON | Same crash class as #7 (`complexity.get("stories")` on non-dict). |
| 10 | commands/orchestrator_epic_agents.py:406 | asset_file | agents.md embedded JSON | Like #8; no shape guard before `.get("stories")`. |
| 11 | commands/orchestrator_epic_agents.py:635 (`parse_agent_config`) | CLI json string | agent-config dict | Tolerant of non-dict perTask but **no guard on `complexityOverrides`** — same crash as #5. |
| 12 | core/telemetry_events.py:307 (`parse_event`) | subprocess_stdout/jsonl | typed event lines | Discriminator hardened; **dataclass fields not runtime-typechecked** — e.g. `cost_usd:"foo"` parses fine (downstream `_compute_spent` filters; other consumers may not). |
| 13 | core/audit.py:217 (`_read_last_record`) | asset_file (audit.jsonl) | last record dict | Hardened — required-field + tag/seq guards. |
| 14 | core/audit.py:420 (`verify`) | asset_file | full chain walk | Hardened. |
| 15 | core/runtime_policy.py:116 / :228 (`load_policy_snapshot`/`_read_json`) | asset_file (policy.json) | policy snapshot | Type-guarded to dict; no length cap. |
| 16 | core/run_identity.py:55 | asset_file (active marker) | run-id correlation marker | Defended (returns "" on non-dict). |
| 17 | core/budget_ceilings.py:239 (`parse_ceilings_config`) | asset_file (workflow.json) | budget ceilings | Tolerant; returns [] on every parse fault. NaN/Inf cost filtered. |
| 18 | core/success_verifiers.py:230 (`_load_review_contract`) | asset_file | review contract sidecar | Type-guarded to dict via PolicyError. |
| 19 | core/utils.py:218 (`parse_string_list_literal`) | CLI string | string-list literal | Returns None on non-list-of-str — safe. |
| 20 | core/utils.py:238 (`extract_json_line`) | subprocess_stdout (model output) | first valid JSON object substring | trims to 150 lines but **a single 100MB line** is still re-scanned with `re.findall`. |
| 21 | core/common.py:159/170 (`unquote_scalar`/`parse_string_list_literal`) | YAML scalar | unquote helper | Localised; safe. |
| 22 | core/stop_hooks.py:223 (`_read_json_object`) | asset_file (settings.json) | Claude hook config | Type-guarded; HookConfigError on non-dict. |
| 23 | commands/state.py:68 | CLI json string | state-build config | json.JSONDecodeError caught; **no type guard** — `config.get("epic")` on a non-dict crashes downstream. |
| 24 | commands/orchestrator_epic_agents.py:332 (`complexity.get`) | asset_file | complexity bundle | Crashes on non-dict (duplicate with #9). |
| 25 | commands/orchestrator.py:314,380 (marker reads) | asset_file (marker) | active-run marker | Defended (isinstance(dict) checks at :384). |
| 26 | commands/tmux.py:50 / basic.py:154 | asset_file (marker) | marker for heartbeat | Defended (isinstance dict). |
| 27 | core/tmux_runtime.py:205 / :1327 | asset_file (session state) | tmux session-state json | Defended (isinstance dict, returns {}). |
| 28 | core/epic_parser.py:105 | asset_file (complexity-rules) | rule list | Hardened — raises ValueError on non-dict. |
| 29 | commands/agent_config_cmd.py:31 | CLI json string | preset save payload | Catches JSONDecodeError; **no type guard** — accepts non-dict as preset.config. |
