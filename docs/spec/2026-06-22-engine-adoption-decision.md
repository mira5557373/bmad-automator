# Engine Adoption Decision — N6 Architectural Call

**Status:** advisory — recommendation + plan; no code changes in this commit
**Author:** N6 architectural-decision run (2026-06-22)
**Predecessors:** SASA+ Wave 1+2+3 landing (commit `f4eabba`), CLIProfile (M32), policy_translator bridge (M39), Phases 4-6 deferral memo (`docs/spec/2026-06-21-phases-4-6-deferral.md`)
**Audience:** the single-operator maintainer of `bmad-story-automator`

## TL;DR

**Recommendation: PATH_B — keep the registry-of-callables dispatcher; add a
small in-process HookBus-compat layer to satisfy multi-CLI dispatch and the
plugin contract.** Path A (full Engine adoption) would replace ~3,000 LOC of
deterministic, well-tested orchestration (gate_orchestrator + verifiers +
runtime_policy + commands) with bmad-auto's 1,454-LOC Engine class and ~2,500
LOC of supporting modules (registry, plugins, statemachine, journal, runs,
adapters). The capability gain — pluggable lifecycle hooks across 14+ stages,
multi-CLI dispatch, worktree isolation — is real, but most of it duplicates
infrastructure we already have (`gate_orchestrator`, `gate_audit`,
`trust_boundary`, `tmux_runtime`, `policy_translator`). Path B delivers the
same end-user capabilities (multi-CLI dispatch, hookable lifecycle) in
~600-900 LOC of additive code, preserves our deterministic gate program,
keeps the existing 3,763-test baseline green, and avoids importing bmad-auto's
non-deterministic global state (signal-handler ownership, process-wide
`_stop_signals_owner`, mutable PluginRegistry validation).

## Why this question matters now

We have just shipped 33 milestones (SASA+ Waves 1+2+3) that brought our
codebase to bmad-auto *contract* compatibility — CLIProfile, policy
translator, ADR-29 evaluator, phase-shaped budgets, RAMR pre-flight,
overspend classification. Every one of those milestones was additive: we did
not rip out our own dispatcher to plug in bmad-auto's. The remaining
architectural question is whether the *next* wave (N6–N12 in the integration
plan) should continue that additive direction or whether we should now pivot
to importing bmad-auto's `Engine` class wholesale and rewiring our verifiers
and gate program on top of it.

The decision is load-bearing for three reasons:

1. **Stop-energy compounding.** If we adopt Engine and then need to back out,
   every milestone after the pivot point becomes a rebase liability. The
   deferral memo from 2026-06-21 already records that Phases 4-6 of the
   earlier autonomous run *did not* adopt bmad-auto's TUI, CLIProfile
   dispatch, or plugin overlay — they shipped additive shims instead. A
   pivot now would invalidate that working baseline.
2. **Trust-boundary surface.** Our `core/trust_boundary.py` enforces a
   fail-closed host-context invariant on every gate orchestrator entry
   point. bmad-auto's Engine has no equivalent contract — its
   `_install_stop_signals` mutates process-global state
   (`Engine._stop_signals_owner`), and `PluginRegistry.validate` runs
   plugin-supplied Python on startup. Folding that into our trust model
   requires explicit, dated waivers; deferring the decision delays the
   waiver discussion past three or four more milestones.
3. **Single-operator economics.** The user is one trusted operator on their
   own VPS (`singleuser-threat-model.md`). Path A's plugin sandbox + signal
   ownership + workspace isolation machinery is built for a multi-team CI
   server where untrusted plugin authors and concurrent runs matter.
   Path B sizes the surface to the actual threat model.

## The two paths

### Path A — Full Engine adoption

#### What it changes (concrete file-level inventory)

**Modules added** (copied or ported from `external/bmad-auto/src/automator/`):

| New local module | Source | LOC | Purpose |
| --- | --- | --- | --- |
| `core/engine.py` | `engine.py` | 1,454 | Deterministic control loop, signal handling, workspace gating, session dispatch |
| `core/policy_dc.py` | `policy.py` | 656 | Frozen-dataclass policy surface (Policy, GatesPolicy, …) |
| `core/plugins/bus.py` | `plugins/bus.py` | 251 | HookBus dispatch with declarative + python hooks |
| `core/plugins/context.py` | `plugins/context.py` | ~150 | HookContext, Veto, MUTABLE_FIELDS |
| `core/plugins/registry.py` | `plugins/registry.py` | ~300 | PluginRegistry build / validate / seed |
| `core/plugins/model.py` | `plugins/model.py` | ~200 | LoadedPlugin + manifest model |
| `core/statemachine.py` | `statemachine.py` | ~150 | Phase transitions (`advance`) |
| `core/journal.py` | `journal.py` | ~250 | Append-only event log |
| `core/runs.py` | `runs.py` | ~200 | tmux session lifecycle (`kill_session`) |
| `core/escalation.py` | `escalation.py` | ~300 | `decide_dev` / `decide_review_session` |
| `core/model.py` | `model.py` | ~250 | StoryTask, RunState, Phase |
| `core/workspace.py` | `workspace.py` | ~400 | Workspace + worktree machinery |
| `core/verify_bauto.py` | `verify.py` | ~600 | Git plumbing (`safe_rollback`, `merge_branch`) |
| `core/adapters/base.py` | `adapters/base.py` | ~120 | `CodingCLIAdapter`, `SessionResult` |

**Modules deleted or gutted:**

- `core/gate_orchestrator.py` (586 LOC) — replaced by Engine's `_drive_story` + `_review_and_commit` + `_run_isolated`
- `core/success_verifiers.py` (450 LOC, VERIFIERS registry) — replaced by Engine's `_verify_dev_artifacts` / `_verify_review` override seams plus the `verify_commands_outcome` path
- `core/runtime_policy.py` (622 LOC) — replaced by `policy_dc.loads()` + a thin compat shim
- `core/cli_profile.py` (214 LOC) — folded into adapters/base.py's CLI-specific subclasses
- `core/bauto_bridge/policy_translator.py` (186 LOC) — no longer needed; we *are* the bauto policy now
- `commands/orchestrator.py` + `commands/orchestrator_parse.py` + `commands/orchestrator_epic_agents.py` (~1,500 LOC combined) — replaced by Engine's loop + sprint-status parser
- `commands/gate_cmd.py` — folded into a thin `commands/gate_compat.py` that calls Engine's verify path

**Modules to rewrite (not just delete):**

- `core/trust_boundary.py` (assert_host_context) — needs a *new* contract that approves Engine's signal-handler ownership + plugin imports
- `core/telemetry_emitter.py` + every call site in `commands/` — bmad-auto journals through `Journal.append(kind, **fields)`, not our typed `TelemetryEvent` ADT. Either we keep our ADT and write a Journal→TelemetryEmitter adapter, or we delete our ADT and inherit Journal's structural-only contract.
- All 14 collectors under `core/collectors/` — they currently consume our `CollectorConfig` from `runtime_policy`; they would need to consume `Policy` dataclasses instead, or we keep `runtime_policy` as a compatibility view (in which case we have two policy systems running in parallel).

**Tests impacted:**

- Every test under `tests/integration/` that drives the orchestration loop directly (≈350 tests) needs to be rewritten against Engine's `_loop`
- Every gate-program test that asserts on the `production_ready_gate` verifier output (≈800 tests) needs to be rewritten because Engine has no concept of a `VERIFIERS` registry — its verification is overrideable methods, not callable lookup
- Every CLI test in `tests/cli/` that asserts on `commands/gate_cmd.py` output needs to be rewritten
- ≈600 tests would need port; ≈200 are likely to be deleted because Engine's design subsumes what they assert

Rough net delta: **+4,000 LOC ported, -3,800 LOC removed, ~1,600 tests churned.**

#### Cost estimate

- **Lift-and-port phase:** 3-4 weeks of full-time work for one engineer.
  Includes resolving every place where bmad-auto's `Policy` schema differs
  from our `runtime_policy` schema (gate_program, profiles,
  collector_config, risk_profile, mitigation_debt — all six of those tables
  have no equivalent in bmad-auto and would need to be carried as "extra
  tables" the way we carry `[plugins]` settings).
- **Trust-boundary re-derivation:** 1 week. The current
  `assert_host_context` invariant covers every entry point to a collector
  (m3 collector_checkout); Engine has no equivalent, so we have to either
  retrofit the assertion into every Engine method that spawns a session or
  shrink the trust boundary, which would be a policy regression.
- **Test re-port:** 2-3 weeks. The 3,763-test baseline contains ~1,600
  tests that depend on our orchestrator and gate-orchestrator shapes;
  every one of them needs an Engine-shaped equivalent or an explicit
  deletion with justification.
- **Operator validation:** 1-2 weeks. The factory only meets its
  determinism contract once we have re-run the audit floor (Phase 0) and
  the post-collect adjudicator tests against the new dispatcher.

**Total: 7-10 engineer-weeks.**

#### Capability gains

1. **Pluggable lifecycle hooks at 14+ stages** (`pre_dev_phase`, `pre_session`,
   `post_session`, `pre_review_phase`, `pre_commit`, `post_commit`,
   `pre_worktree_setup`, `pre_ready_gate`, `pre_epic_boundary`, …). Today
   we have *no* hook surface; a new collector or gate must be wired into
   the orchestrator by hand.
2. **Worktree isolation** — `_run_isolated` lets each story run in a fresh
   `git worktree` branched off the target. Our current dispatcher works
   in-place on the checked-out tree.
3. **Multi-CLI dispatch** at the `adapters` layer (claude, codex, gemini,
   cursor) with per-stage adapter overrides (`adapter.dev.name = "codex"`).
4. **HookBus failure isolation** — a Python plugin that raises is caught
   and journalled, the plugin is disabled for the rest of the run, and the
   run continues. We have no equivalent today.
5. **Resumable runs** — `_finish_inflight` reconstructs in-flight state on
   restart, including a half-built worktree. Today we have crash recovery
   *only* for the gate sub-step, not for the orchestration loop as a whole.

#### Risk profile

- **(R-A1) Global signal-handler ownership.** Engine installs SIGTERM/SIGINT
  handlers at the process level (`_stop_signals_owner`). If we import
  Engine into a test runner that already binds signal handlers (unittest
  on Windows does), the handler swap deadlocks the test. Bmad-auto guards
  this with a `try/except ValueError`; we would need our own integration
  test that proves the swap is idempotent across all our test runners.
- **(R-A2) Untrusted plugin code path.** `PluginRegistry.build` imports
  every Python plugin module declared in `[plugins]`. Our trust model is
  "one operator, one VPS, no untrusted code." Engine's plugin system was
  designed for an external author shipping a plugin folder — bringing it
  in means we are now hosting an import-time arbitrary-code-execution
  surface even if the operator never enables a plugin.
- **(R-A3) Determinism regression.** Our gate program is deterministic by
  contract (same inputs → same verdict). Engine's `_run_workflows` emits a
  fresh session per workflow-bound plugin; a plugin order change between
  runs would change the session sequence and (downstream) the token
  budget, even when the input story is identical.
- **(R-A4) Journal-vs-Telemetry duality.** Our typed `TelemetryEvent` ADT
  is gated on M01 (do not touch outside its owning milestone). Engine's
  `journal.append(kind, **fields)` is structurally untyped. Either we
  proxy Engine's calls back into the ADT (extra adapter we have to
  maintain) or we suppress the ADT contract entirely (M01 guardrail
  breach, requires explicit waiver).
- **(R-A5) bmad-auto submodule drift.** `external/bmad-auto/` is a git
  submodule pinned to a SHA. Once we *port* (not link) those files into
  our tree, we own them — any upstream bugfix has to be hand-merged. The
  submodule was vendored for *contract* observation, not for
  production-time consumption.

### Path B — Compat-shim posture (continue current direction)

#### What stays the same

- `core/gate_orchestrator.py` keeps owning the gate program lifecycle
  (collect, adjudicate, route verdict, park/resume, mitigation debt). All
  3,763 existing tests stay green by construction; no test churn.
- `core/runtime_policy.py` keeps owning the policy schema. Gate
  configuration, profiles, and collector_config stay in their current
  dict-of-dicts shape (which the gate-program collectors already consume).
- `core/trust_boundary.py` keeps its `assert_host_context` invariant on
  every collector entry point; no rewrite needed.
- `core/telemetry_events.py` keeps its typed ADT (M01 guardrail intact).
- `core/cli_profile.py` (M32) is already a working
  multi-CLI profile schema; the missing piece is a dispatcher that *uses*
  it, not a redesigned schema.
- `core/bauto_bridge/policy_translator.py` (M39) keeps its role as the
  closed-set bauto-policy bridge for operators who want to interoperate
  with a bmad-auto deployment without committing to Engine.

#### What needs to be added

1. **HookBus-compat layer** (~250 LOC). A new `core/hook_bus.py` that
   mirrors bmad-auto's `HookBus.active(stage)` + `emit(stage, ctx)`
   contract but drives our existing dispatcher's lifecycle stages. Active
   stages: `pre_dev_phase`, `post_dev_verify`, `pre_review_phase`,
   `post_review_result`, `pre_commit`, `post_commit`. (Six stages, not
   bmad-auto's 14+; the remaining eight are worktree-related and we don't
   adopt worktree isolation in this path.)
2. **In-process plugin registry** (~200 LOC). `core/plugins.py` —
   declarative-only (no Python import path; the trust-boundary contract
   forbids it). Plugins are TOML files in `_bmad/plugins/<name>.toml` that
   declare `hooks = [{stage = "...", cmd = "...", timeout = 30}]`. Cmd
   runs out-of-process exactly like bmad-auto's `_dispatch_declarative`.
3. **Multi-CLI dispatcher** (~300 LOC). A new
   `core/cli_dispatcher.py` that consumes `CLIProfile` (already shipped in
   M32) and dispatches a session via the registered profile's
   `tmux_runtime` adapter. The dispatcher chooses dev/review profiles per
   the existing `policy.adapter.dev.name` / `adapter.review.name` keys
   (which `policy_translator` already round-trips). Stop-hook detection
   continues to use our existing `lie_detector` baseline-commit
   verification.
4. **Optional: Action enum** (~100 LOC, deferral memo Phase 6's starter).
   A `core/action_enum.py` Literal type so verifier call sites that today
   pass strings ("done"/"remediate"/"park") can narrow to enum values
   without changing the wire format.

Net delta: **+850 LOC added, 0 removed, 0 existing tests churned, ~120 new tests for the additive surface.**

#### Cost estimate

- HookBus-compat layer + tests: 3-4 days
- Plugin registry (declarative only) + tests: 3-4 days
- CLI dispatcher consuming CLIProfile: 5-7 days (most of the work is
  wiring stop-hook detection per CLI dialect)
- Action enum starter: 1 day

**Total: 2-3 engineer-weeks.**

#### Capability gains/losses vs Path A

| Capability | Path A | Path B |
| --- | --- | --- |
| Pluggable lifecycle hooks | 14+ stages | 6 stages (the ones we actually drive) |
| Worktree isolation | Yes | No — in-place on checked-out branch (current behavior) |
| Multi-CLI dispatch | Yes (adapter layer) | Yes (CLIProfile + cli_dispatcher) |
| HookBus failure isolation | Yes (Python + declarative) | Declarative-only (Python plugins forbidden by trust model) |
| Resumable runs | Engine `_finish_inflight` (full loop) | Gate-substep only (current behavior) |
| Hook context mutations (`mutate`/`shared`/`veto`) | Yes | Yes (mirrors bmad-auto's stdout-JSON contract) |
| Workflows-as-plugins | Yes | No |
| Plugin enablement allowlist | `[plugins].enabled` | `[plugins].enabled` (same schema, declarative-only) |

The two capabilities Path B *does not* deliver are **worktree isolation**
and **workflows-as-plugins**. The first is a tradeoff against the
single-operator threat model (we work directly on the operator's checked-out
branch; rollback is via `lie_detector` baseline + a manual `git reset`).
The second is a YAGNI line — we have no demand signal for a plugin to
inject an extra agent session, and the deferral memo from 2026-06-21
already records this as a non-priority.

## Decision criteria

| Dimension | Path A | Path B | Winner | Reasoning |
| --- | --- | --- | --- | --- |
| Engineer-weeks to land | 7-10 | 2-3 | **B** | 3-4x cost ratio for largely-duplicated capability |
| Existing tests churned | ~1,600 | 0 | **B** | A invalidates the audit-floor regression suite; B is purely additive |
| LOC delta | +4,000 / -3,800 | +850 / -0 | **B** | Net +200 vs +850 misleads — A *replaces* working code with imported code we now own |
| Multi-CLI dispatch | Yes | Yes | tie | Both deliver it; A via adapter classes, B via CLIProfile-consuming dispatcher |
| Lifecycle hook surface | 14+ stages | 6 stages | A | A is genuinely richer here; B's six cover the operator-visible stages |
| Worktree isolation | Yes | No | A | A genuine capability gain; weighed against single-operator threat model |
| Determinism preserved | Risk (R-A3) | Yes | **B** | B's gate program retains the same-inputs-same-verdict contract |
| Trust boundary intact | Risk (R-A2) | Yes | **B** | B's plugins are declarative-only; no import-time arbitrary code |
| M01 guardrail intact | Risk (R-A4) | Yes | **B** | B does not touch telemetry_events; A requires explicit waiver |
| Submodule drift risk | Risk (R-A5) | None | **B** | B leaves external/bmad-auto as observable contract, not vendored code |
| Resumable orchestration loop | Yes | No | A | A wins; B keeps current gate-substep-only recovery |
| Operator-visible feature parity with bmad-auto deployments | Full | Wire-compat | A | A *is* bmad-auto; B is wire-compat via policy_translator |
| Reversibility if wrong call | Hard | Easy | **B** | B is additive; rolling back is a `git revert` |

**Tally:** Path B wins 8 of 12 dimensions; the four wins for Path A are
real but address capabilities the single-operator threat model does not
demand.

## Recommendation

**PATH_B — keep the registry-of-callables dispatcher; add a small
HookBus-compat layer + declarative plugin registry + CLI dispatcher
that consumes the existing CLIProfile schema.**

The three strongest reasons:

1. **The 3,763-test baseline is load-bearing.** Path A churns ~1,600 of
   those tests. Each churned test is a place where a subtle invariant
   could regress unobserved. Path B is purely additive: every existing
   test stays green by construction, and the ~120 new tests for the
   compat layer can be reviewed in isolation. The audit-floor regression
   suite (Phase 0) is exactly the kind of contract that should *not* be
   re-derived under a new dispatcher.

2. **The trust-boundary contract is not negotiable in our threat model.**
   `core/trust_boundary.py` exists because the gate program's
   determinism + audit hash chain only mean something if the
   evidence-collection environment is sandboxed. Engine's
   `_install_stop_signals` and `PluginRegistry.build` both touch
   process-global state in ways the current invariant does not cover.
   Path B's declarative-only plugins (subprocess-spawned cmd, no Python
   import) keep the invariant intact without a waiver discussion.

3. **The capability gap is smaller than it looks.** Multi-CLI dispatch is
   the one operator-facing capability that genuinely requires new code,
   and we already shipped CLIProfile (M32) and policy_translator (M39).
   The remaining work — a 300-LOC dispatcher that consumes CLIProfile —
   is small enough to design, implement, and review in a single
   milestone. Adopting Engine to get multi-CLI dispatch is, charitably,
   shooting a fly with a tank.

## Phased plan for Path B

| Milestone | Scope | LOC budget | Effort | Tests added |
| --- | --- | --- | --- | --- |
| **N6.2** | `core/hook_bus.py` — 6-stage HookBus-compat layer with `active()` fast-path, `emit()` dispatch, `HookContext` + `Veto` mirroring bmad-auto's API surface. Wire into `gate_orchestrator` at `pre_collect` / `post_collect` / `pre_evaluate` / `post_evaluate` only (4 stages); add the dev/review/commit stages in N6.3. | ≤300 | 3-4 days | ~30 |
| **N6.3** | Wire HookBus into `commands/orchestrator.py` at `pre_dev_phase` / `post_dev_verify` / `pre_review_phase` / `post_review_result` / `pre_commit` / `post_commit` (6 stages). No new dispatcher logic; just emit + honor veto + record `pre_commit` message rewrites. | ≤200 | 2-3 days | ~25 |
| **N6.4** | `core/plugins.py` — declarative-only plugin registry. Loads `_bmad/plugins/<name>.toml`, validates against `[plugins].enabled` allowlist, exposes `list_plugins()` + `hooks_for(stage)`. Subprocess transport mirrors bmad-auto `_dispatch_declarative` (timeout, stdout-JSON contract, fail-closed). Python plugin path explicitly rejected with `PluginTrustError`. | ≤350 | 4-5 days | ~30 |
| **N6.5** | `core/cli_dispatcher.py` — consumes `CLIProfile` (M32), dispatches a session via `tmux_runtime`, honors `policy.adapter.dev.name` / `adapter.review.name` per-stage overrides. Stop-hook detection: per-CLI dialect map (claude / codex / gemini), falling back to `lie_detector` baseline-commit check. | ≤400 | 5-7 days | ~40 |
| **N6.6** | `core/action_enum.py` — Literal type for verifier actions (`"done"` / `"remediate"` / `"park"` / `"defer"` / `"escalate"`), narrow existing call sites incrementally (no behavior change). | ≤150 | 1-2 days | ~10 |
| **N6.7** | Docs + audit-floor sweep. Update CLAUDE.md "Gate subsystem" section to mention hook_bus / plugins / cli_dispatcher. Add an audit-floor invariant: "no Python plugin import path exists in `core/plugins.py`." | ≤50 | 1 day | ~5 |

**Total: ~1,450 LOC, 16-22 engineer-days, ~140 new tests.** All existing
3,763 tests remain green by construction (additive milestones only).

## Risks + mitigations

- **(R-B1) Stop-hook detection drift.** If Codex's stop-hook contract
  evolves and our dispatcher's dialect map gets stale, a session would
  appear "still running" forever. **Mitigation:** every CLI dispatch
  records a `session_started_at` in the journal; an integration test
  asserts the heartbeat fires within `policy.limits.session_timeout_min`
  and that timeout fires `lie_detector` *and* journals a
  `cli-dispatch-stale` event the operator can grep for.

- **(R-B2) Plugin declarative-only surface is too restrictive.** If a
  future operator wants in-process Python plugins (e.g., for a complex
  workflow we have not anticipated), Path B's `PluginTrustError`
  rejection will block them. **Mitigation:** this is an intentional
  feature, not a bug. The trust-boundary contract is the *reason* we are
  picking Path B; if the threat model changes (multi-operator,
  shared-infra deployment), we revisit and either widen the allowlist
  with a per-plugin signature check or pivot to Path A then.

- **(R-B3) HookBus contract drift vs bmad-auto.** Operators interoperating
  with a bmad-auto deployment via `policy_translator` may see hook
  semantics that differ from bmad-auto's. **Mitigation:** our HookBus
  emits the same `HookContext` shape (run_id, story_key, stage, role,
  phase, branch, agents) and honors the same veto actions (defer / skip
  / pause); document the 8 unmodelled stages (`pre_worktree_setup`,
  `pre_workflow_session`, …) as "no-op on our dispatcher" so a hook
  written against bmad-auto's API never crashes against ours — it simply
  does not fire on the worktree-only stages.

- **(R-B4) Six-stage hook surface is not enough.** If the operator
  discovers they want a hook at `pre_pick_next` (story-selection time),
  Path B has no place to wire it. **Mitigation:** the HookBus
  infrastructure scales linearly — each new stage is one `if
  self._bus.active(stage):` guard + one `_emit` call. Adding a stage in
  a future milestone is a contained edit, not a re-architecture.

- **(R-B5) policy_translator schema divergence.** As we add new
  bmad-auto tables to be translatable (e.g. `[adapter.dev]`,
  `[adapter.review]`, `[plugins.<name>]`), the bridge has to stay in
  sync. **Mitigation:** the bridge already has a closed-set guard
  (`_reject_unknown_tables`); every new bmad-auto table addition is
  forced through an explicit milestone with its own integration test.
  We catch drift at translation time, not at runtime.

## Cross-references

- `external/bmad-auto/src/automator/engine.py` (1,454 LOC) — Path A's source of truth
- `external/bmad-auto/src/automator/policy.py` (656 LOC) — frozen-dataclass policy surface
- `external/bmad-auto/src/automator/plugins/bus.py` (251 LOC) — HookBus + Veto contract we mirror in Path B
- `skills/bmad-story-automator/src/story_automator/core/gate_orchestrator.py` (586 LOC) — current dispatcher
- `skills/bmad-story-automator/src/story_automator/core/success_verifiers.py` (450 LOC) — current `VERIFIERS` registry
- `skills/bmad-story-automator/src/story_automator/core/runtime_policy.py` (622 LOC) — current policy loader
- `skills/bmad-story-automator/src/story_automator/core/cli_profile.py` (214 LOC, M32) — multi-CLI schema (ready for Path B's dispatcher)
- `skills/bmad-story-automator/src/story_automator/core/bauto_bridge/policy_translator.py` (186 LOC, M39) — bauto policy bridge
- `docs/spec/2026-06-21-phases-4-6-deferral.md` — earlier deferral memo (TUI + CLIProfile + Action enum)
- `CLAUDE.md` "Gate subsystem" section — invariants every collector honors
- `~/.claude/projects/.../memory/singleuser-threat-model.md` — the threat model that justifies the declarative-only plugin constraint

---

**Decision pending operator confirmation.** This document is advisory; no
code changes were made in the commit that introduces it. If the operator
accepts the recommendation, the next milestone is **N6.2** (HookBus-compat
layer) per the phased plan above.
