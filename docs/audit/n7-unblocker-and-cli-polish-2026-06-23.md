# N7 unblocker (usage parsers + cost attribution) + CLI polish (lineage top-level) — status report

> Workflow: `n7-unblocker-and-cli-polish` (parallel: N7 unblocker || CLI polish)
> Branch: `bma-d/integration-all`
> Baseline at start: `cf4b71a` (c1-followup-and-c2-cli-complete, 4268 tests green)
> Tip at finish: `7302d54` (4312 tests green)

## TL;DR

Two follow-ups landed in sequence on `bma-d/integration-all`, each tagged
on shipping:

- **N7 unblocker (`compat-n7-usage-parsers-and-cost-attribution`)** —
  ships the substrate that C3 (per-collector cost attribution on gates)
  will consume. Two purely-new modules:
  - **`core/usage_parsers/`** — uniform parser package with four
    dialects. Real `claude-jsonl` parser; `codex-rollout` and
    `gemini-chat` stubs returning zero metrics; `none` null parser for
    the disabled `cli_id`. Closed registry `KNOWN_PARSERS` maps the
    same `cli_id` vocabulary used by `cli_dispatcher` / profile
    composer onto a `PARSER_ID`. `get_parser(cli_id)` raises
    `ParseError` on unknown ids — no silent fallback.
  - **`core/innovation/cost_attribution.py`** — frozen
    `CollectorCostShare` dataclass and three attribution modes
    (`uniform`, `duration-weighted`, `tool-call-weighted`). The
    sum-of-shares == session-total invariant is preserved exactly for
    integer token counts; float drift on weighted modes is absorbed
    into the final share so the rollup stays bit-exact against the
    parsed session.
  - **Zero orchestrator wiring.** C3 wiring (calling these parsers from
    the production gate after collectors return, then attaching a
    `gate_cost_breakdown` block to `GateFile`) is explicitly deferred
    to the C3 milestone — the N7 unblocker only ships the substrate.

- **CLI polish (`compat-cli-polish-lineage-top-level`)** — operators
  could only reach the C2 lineage query CLI via the verbose
  `story-automator orchestrator-helper lineage <sub>` form. Two
  improvements ship in one commit:
  - **`lineage` registered as a top-level command.** Both
    `story-automator lineage <sub>` (new) and
    `story-automator orchestrator-helper lineage <sub>` (back-compat,
    preserved) route through the same `lineage_dispatch` function — no
    duplicated logic.
  - **`--help` polish across the subcommand tree.** `_build_parser`
    accepts an optional `prog` so help renders cleanly at every entry
    point; each subparser gained a one-paragraph `description`
    alongside the existing `help` summary; the new `_ParseHelp`
    sentinel lets argparse's `--help`/`-h` exit cleanly with 0 instead
    of emitting "missing --project-root" error JSON; and bare
    `lineage --help` prints the top-level parser help (no more legacy
    `_usage()` banner with exit 1).

Tests rose 4268 → 4312 (+44). Ruff clean. Audit-floor invariants still
26-green. No frozen-surface symbol changed; new surface only
(`core/usage_parsers/` package, `core/innovation/cost_attribution.py`,
one additive top-level CLI registration). No new dependency.

## N7 unblocker outcome (parsers + cost-attribution substrate; C3 wiring is future)

Commit `5155851` — `feat(n7): unblocker — M50 usage parsers + cost-attribution helper (substrate for C3)`.
Tag `compat-n7-usage-parsers-and-cost-attribution`.

### What it adds

- **New package `core/usage_parsers/`** (all stdlib, no new deps):
  - `types.py` — `UsageMetrics` dataclass (`input_tokens`,
    `output_tokens`, `cache_creation_tokens`, `cache_read_tokens`,
    `total_tokens`, `tool_call_count`, `duration_s`) plus the
    `ParseError` exception type.
  - `claude_jsonl.py` — real parser for the Claude Code stop-hook
    transcript dialect. Tolerant: malformed lines are skipped silently;
    a fully unparseable input reads as zeros (never raises during
    parsing).
  - `codex_rollout.py` — stub returning `UsageMetrics` zeros, ready to
    grow when Codex CLI rollout lands.
  - `gemini_chat.py` — stub returning `UsageMetrics` zeros, ready for
    Gemini CLI chat-mode transcripts.
  - `none.py` — null parser for the explicit `cli_id="none"` disabled
    branch.
  - `__init__.py` — closed `KNOWN_PARSERS: dict[str, str]` mapping
    `cli_id` (`claude-code`, `codex`, `gemini-cli`, `none`) to
    `PARSER_ID`. `get_parser(cli_id)` raises `ParseError` on any
    other value — the registry is the single source of truth for
    "what CLIs are recognized in this build."

- **New module `core/innovation/cost_attribution.py`** (~299 LOC, under
  the 500-LOC soft cap):
  - `CollectorCostShare` — frozen dataclass capturing the share of
    each token bucket assigned to one collector, plus a
    `collector_name` field.
  - `attribute_uniform(session, collector_names)` — equal split across
    every collector named.
  - `attribute_duration_weighted(session, collector_durations)` —
    proportional to wall-clock seconds, with the final share absorbing
    float-rounding drift so sum-of-shares stays exactly equal to
    `session.total_tokens` for integer-token sessions.
  - `attribute_tool_call_weighted(session, collector_tool_calls)` —
    proportional to subprocess invocations; same float-drift absorption
    as duration mode.

### Frozen-surface rule compliance

- `core/usage_parsers/` is a brand-new package — no frozen surface to
  honor.
- `core/innovation/cost_attribution.py` is a brand-new module —
  ditto.
- `core/innovation/ramr.py` was not touched (consumed read-only per
  hard guardrail).
- `core/telemetry_events.py` was not touched (M01-only per hard
  guardrail).
- No existing CLI registration was modified.

### Tests

31 new tests across two files (4268 → 4299 after the N7 unblocker):

- `tests/test_usage_parsers.py` (18 tests) — registry round-trip;
  unknown-`cli_id` raises `ParseError`; `claude_jsonl` parses single
  message, multiple messages, tool-call counts, cache-read /
  cache-creation tokens, duration extraction; malformed JSON lines
  skipped; empty input parses as zeros; stubs return zeros without
  raising; `none` parser returns zeros.
- `tests/test_cost_attribution.py` (13 tests) — `CollectorCostShare`
  is frozen; uniform attribution splits evenly; uniform handles
  zero-collector edge case; duration-weighted matches expected ratios;
  tool-call-weighted matches expected ratios; sum-of-shares ==
  session-total for integer tokens (the key invariant); float drift
  absorbed into final share on weighted modes; empty input handled;
  single-collector session reads identically across all three modes.

## CLI polish outcome (lineage as top-level; --help across subcommands)

Commit `7302d54` — `feat(cli): wire lineage as top-level command + polish --help`.
Tag `compat-cli-polish-lineage-top-level`.

### What it adds

- **`lineage` is now a top-level command.** `cli._command_registry()`
  gains the additive entry `"lineage": lineage_dispatch`. The legacy
  `orchestrator-helper lineage` path continues to dispatch to the
  same callable, so no operator script breaks.
- **`lineage_cmd.py` argparse polish:**
  - `_build_parser(prog="lineage")` — `prog` defaults to the
    top-level command name so `story-automator lineage --help` renders
    a clean banner.
  - Every subparser now carries a one-paragraph `description` in
    addition to the pre-existing `help` summary, so per-subcommand
    `--help` (e.g. `story-automator lineage verify --help`) prints
    useful prose explaining the action's semantics.
  - `_ParseHelp` sentinel exception — when argparse exits 0 after
    printing `--help`/`-h` for a subcommand, the sentinel lets
    `lineage_dispatch` return 0 cleanly instead of falling into the
    "missing --project-root" error path.
  - Bare `story-automator lineage --help` / `lineage -h` now invokes
    the top-level parser's `print_help()` and returns 0, rather than
    falling through to the legacy `_usage()` banner that returned 1.

### Frozen-surface rule compliance

- The top-level CLI registration is additive — no existing entry
  renamed, removed, or repurposed.
- `lineage_dispatch` is the same callable used by the legacy
  `orchestrator-helper lineage` path; back-compat preserved.
- No telemetry, no audit-chain, no gate-schema surface touched.

### Tests

13 new tests in `tests/test_lineage_cli_top_level.py`:

- Top-level registration: `lineage` appears in `_command_registry()`
  and is byte-identical to `lineage_dispatch`.
- Help exit codes: `story-automator lineage --help`,
  `story-automator lineage <sub> --help`, and the bare `lineage` form
  all exit 0.
- Help body: lists every documented subcommand
  (`show / entry / stats / verify / orphans`) and surfaces the
  `--project-root` flag.
- Regression fence: every pre-existing top-level command (orchestrator,
  orchestrator-helper, state, tmux, validate-story-creation, basic,
  etc.) remains registered.
- Process boundary: `python -m story_automator lineage --help` exits 0
  end-to-end (catches argparse-formatter edge cases that only show up
  outside the in-process test harness).

## Final state

- **HEAD:** `7302d54` — `feat(cli): wire lineage as top-level command + polish --help`.
- **Tests:** **4312 total**, 0 failing, 2 skipped (pre-existing).
  `+44` net from the 4268 baseline (+31 from N7 unblocker, +13 from
  CLI polish).
- **Ruff:** clean.
- **Audit-floor invariants:** 26 / 26 green
  (`tests/test_audit_regression.py`).
- **Frozen-surface compliance:** zero existing symbol renamed, removed,
  or signature-narrowed; one purely-new package
  (`core/usage_parsers/`), one purely-new module
  (`core/innovation/cost_attribution.py`), and one additive top-level
  CLI registration. `core/telemetry_events.py` untouched.
  `core/innovation/ramr.py` untouched (read-only consumer per hard
  guardrail).
- **Tags shipped this workflow:**
  - `compat-n7-usage-parsers-and-cost-attribution`
  - `compat-cli-polish-lineage-top-level`

## What remains tracked

### C3 wiring — the actual cost-attribution-on-gates feature

The N7 unblocker explicitly ships the *substrate* (parsers +
attribution helpers), not the orchestrator wiring. C3 still needs:

- Hook the parsers into the production-gate path so each child session
  produces a parsed `UsageMetrics` instance.
- Aggregate per-collector wall-clock + subprocess CPU + tool-call
  counts during `run_production_gate`'s collector loop.
- Call one of the three attribution modes (probably
  `attribute_duration_weighted` as the default; configurable in
  profile) to produce a per-collector `CollectorCostShare` list.
- Attach the rollup as a `gate_cost_breakdown` block on `GateFile`
  (schema addition + canonical-JSON ordering rules + a fresh
  audit-floor invariant pinning the structural shape).
- Plumb a `gate cost` subcommand under the gate CLI for operator
  inspection.

Estimated as a one-milestone follow-up; unblocked by this workflow.

### C4 deferred

Compliance pack (SOC2 / ISO27001 / HIPAA evidence map) — still
deferred. Single-user-VPS threat model does not warrant the
operational overhead; revisit when an enterprise customer asks.

### C5 needs A9 corpus

Self-improving gate (gate rules trained on prior verdicts) — still
blocked by the A9 multi-month gate corpus. Tracked for after A9
corpus stabilises.

### G-class multi-week

G1 / G3 / G6 / G8 follow-ups recorded in
`docs/audit/k2-and-c2-2026-06-23.md` and earlier reports remain
multi-week initiatives; none touched by this workflow.

### Push to remote

This workflow shipped against `bma-d/integration-all` locally. The
local-only backlog continues to grow across workflow archives. Per the
operator push-cadence convention, batched-push to
`origin/bma-d/integration-all` is a separate operator step — this
workflow does not push.

### Audit-floor health

26 invariants. No new invariant added by this workflow. The N7
unblocker introduces a pure-parsing surface (no audit-chain emission,
no telemetry surface). The CLI polish is operator-facing argparse
plumbing only. The next candidate for a new invariant is the C3
wiring milestone (when `gate_cost_breakdown` lands on `GateFile`),
which will introduce a fresh canonical-JSON sub-block whose
structural shape warrants a pin.
