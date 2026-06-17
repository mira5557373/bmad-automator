# BMAD Full-Lifecycle Orchestrator — Milestone Spec

**Status:** Draft for approval (2026-06-17)
**Extends:** `bmad-story-automator` (which today automates only BMM Phase 4, the per-story sprint loop)
**Goal:** Drive *every* BMAD phase autonomously with human-approval checkpoints, covering the
BMM core lifecycle + TEA quality gates + the WDS design track, for both greenfield and brownfield
projects, by adding a **macro lifecycle layer** on top of the existing (hardened, validated) sprint engine.

---

## 1. Locked decisions (operator, 2026-06-17)

| Decision | Choice |
|---|---|
| Autonomy model | **Autonomous drafting + human-approval gates** (pause after brief / PRD / architecture; draft-with-assumptions for interactive workflows) |
| Scope | **BMM phases 1–5 + TEA gates + WDS design track** |
| Project mode | **Both** greenfield (idea→code) and brownfield (existing codebase) |
| Build approach | **Extend** — a macro layer that delegates Phase 4 to the existing sprint engine |
| Sequencing | Spec now; Tier-3 validation parked until native WSL claude is installed |
| First buildable slice | **Phase 3→4 bridge** (epics/stories → sprint) |

## 2. Foundational thesis

"Automate all phases" ≠ "remove the human." BMAD's own ceilings (Analysis 5–20%, Planning 30–50%,
Solutioning 40–60%, Implementation 60–80%, Retro 10–30%) mean the upstream phases cannot be fully
autonomous. The orchestrator automates each phase's **drafting + validation + handoff**, and **pauses
at the points where a wrong artifact cascades** (brief → PRD → architecture). Gates cap blast radius
and are a feature. BMAD ships per-phase validators (`bmad-validate-prd`,
`bmad-check-implementation-readiness`) that the orchestrator reuses as deterministic phase verifiers.

## 3. Architecture

### 3.1 Macro layer over micro engine
The current product is the **Phase-4 executor**. The new layer is a **phase-DAG scheduler + gate
manager** that invokes the executor for any node and delegates Phase 4 to the existing sprint loop.

```
lifecycle-orchestrator (NEW macro layer)
  ├─ lifecycle-status.yaml      # which nodes done/approved/pending; per-run state
  ├─ lifecycle-policy.json      # the phase DAG: node defs + edges (source of truth)
  ├─ phase-runner               # spawn child agent for node.skill, monitor, verify, hand off
  │     └─ (node.track=bmm,phase=4) ──► delegates to EXISTING sprint orchestrator
  ├─ phase verifiers            # generalize success_verifiers.py (+ wrap BMAD validators)
  ├─ approval-gate primitive    # await-approval / approve / reject(+notes → course-correct)
  ├─ entry-mode router          # greenfield→W1/B1 ; brownfield→document-project then B2/B3
  └─ artifact bus               # thread each node's output forward as input context
```

### 3.2 Reuse (unchanged) vs net-new
- **Reused:** tmux spawn/monitor/capture, `success_verifiers` pattern, atomic state + marker +
  heartbeat + `run_id` telemetry, agent-selection/calibration, trust-but-verify, crash detection.
- **Net-new:** the 6 macro components above.

### 3.3 lifecycle-policy.json — node schema
```jsonc
{
  "nodes": {
    "B2-prd": {
      "track": "bmm", "phase": 2,
      "skill": "bmad-create-prd",
      "validator_skill": "bmad-validate-prd",     // optional deterministic validator
      "deps": ["B1-brief", "W2-trigger-map"],     // upstream node ids
      "input_artifacts": ["docs/product-brief.md"],
      "output_artifact": "docs/prd.md",
      "verifier": "prd_valid",                    // success_verifier name
      "gate": "human",                            // human | auto
      "modes": ["greenfield", "brownfield"],
      "agent_role": "pm",
      "interactive": true                         // run draft-with-assumptions, flag at gate
    }
    // ... one entry per node (see §4)
  },
  "entry": {
    "greenfield": ["B1-brief", "W1-project-brief"],
    "brownfield": ["B0-document-project"]
  }
}
```

### 3.4 Scheduler semantics
A node is **runnable** when every `deps` node is `complete` **and approved** (if gated) and all
`input_artifacts` exist. Run → produce `output_artifact` → run `verifier` (and `validator_skill` if
present) → if `gate=human`, emit `LifecycleGatePending` and **pause**; else advance. Topological over
the DAG; multiple runnable nodes may execute (bounded concurrency, reusing the tmux runtime).

### 3.5 Approval-gate protocol
- `lifecycle-helper await-approval --node X --artifact <path>` → records pending gate, emits telemetry,
  returns `PAUSED` (the lifecycle loop stops cleanly, like a deliberate stop-hook).
- Operator reviews the artifact, then `lifecycle-helper approve --node X` **or**
  `lifecycle-helper reject --node X --notes "<corrections>"`.
- **reject → course-correction:** re-run node X (or a named upstream node) with `notes` injected as
  additional agent context; reuses `bmad-correct-course` where applicable.

### 3.6 The three-track DAG
```
GREENFIELD ─┐                                     BROWNFIELD ─┐
            ▼                                                  ▼
 WDS design        BMM dev                         TEA quality
 ─────────         ───────                          ───────────
 W1 brief    ─────► B1 analysis/brief        (brownfield: B0 document-project first)
 W2 trigger  ─────► B2 PRD          🧑gate
 W3 scenarios ────► B3 architecture 🧑gate
 W4 ux-design ────► B3 epics+stories 🧑gate ─────► T1 test-design (per epic)
 W5 agentic-dev ◄── B4 SPRINT (existing engine) ◄─ per story: dev [+WDS UI]
 W6 assets          B5 retrospective
 W7 design-system ─►(feeds future epics)
 W8 evolution                                ─────► T2 nfr + trace GATE 🚦 (P0 fail → no release)
```

## 4. Node catalog

| Node | Track/Phase | Skill | Verifier | Gate |
|---|---|---|---|---|
| B0-document | bmm/pre (brownfield) | `bmad-document-project` | project-context exists | auto |
| B1-brief | bmm/1 | `bmad-product-brief` (+research) | structural/[TBD] | 🧑 |
| B2-prd | bmm/2 | `bmad-create-prd` → `bmad-validate-prd` | `prd_valid` | 🧑 |
| B3-arch | bmm/3 | `bmad-create-architecture` | structural | 🧑 |
| B3-epics | bmm/3 | `bmad-create-epics-and-stories` → `bmad-check-implementation-readiness` | `epics_created` + readiness | 🧑 |
| B4-sprint | bmm/4 | **existing sprint orchestrator** | `success_verifiers` (tests/review) | auto |
| B5-retro | bmm/5 | `bmad-retrospective` | n/a | auto |
| T1-test-design | tea/epic | `bmad-testarch-test-design` | plan exists | auto |
| T2-gate | tea/release | `bmad-testarch-nfr` + `bmad-testarch-trace` | trace PASS (P0) | 🚦 hard |
| W1..W8 | wds/0–8 | `wds-*` (Saga/Freya/Mimir) | per-phase artifact exists | mixed |

## 5. Milestone program (~15 milestones, 4 groups)

### Group F — Foundation (the macro layer)
- **LM01 — Lifecycle data model.** `lifecycle-status.yaml` + `lifecycle-policy.json` schema + loader/
  validator + resume. *Accept:* schema validates, round-trips, resumes mid-lifecycle.
- **LM02 — phase-runner.** Generalize spawn/monitor/verify for one node; Phase-4 delegation hook.
  *Accept:* runs a node end-to-end (mocked agent) → verify → advance; phase-4 node calls the sprint engine.
- **LM03 — phase verifiers.** Wrap `validate-prd` + `check-implementation-readiness`; structural/[TBD]
  verifier; pluggable registry. *Accept:* each verifier pass/fails correctly on fixtures.
- **LM04 — approval-gate primitive.** `await-approval`/`approve`/`reject(+notes)` + course-correct
  loop-back + `LifecycleGate*` telemetry. *Accept:* gate pauses; approve advances; reject re-runs with notes.
- **LM05 — entry-mode router.** Greenfield vs brownfield detection; brownfield runs `document-project`.
  *Accept:* both modes select the correct start node(s).

### Group B — BMM track
- **BM01 — Phase 3→4 bridge (FIRST SLICE, see §6).**
- **BM02 — Phase 2 PRD node** (`create-prd` draft + `validate-prd` + 🧑 gate).
- **BM03 — Phase 1 analysis node** (research + `product-brief` + 🧑 gate).
- **BM04 — Phase 5 retro node** (`bmad-retrospective` at lifecycle end; mostly wiring).

### Group T — TEA track
- **TM01 — test-design @ epic boundary** (feeds story creation context).
- **TM02 — nfr + trace release gate** (P0 FAIL blocks the release node; reuses TEA's PASS/CONCERNS/FAIL).

### Group W — WDS track (largest; last)
- **WM01 — WDS install + config + memory/sync tools** integration.
- **WM02 — WDS design-track orchestration** (Saga ph1–2, Freya ph3–4).
- **WM03 — WDS→BMM artifact handoff** (ux-design/design-system → PRD/arch/story inputs). *Biggest unknown.*
- **WM04 — WDS ph5–8** (agentic-dev overlap, assets, design-system, evolution).

**Build order:** F (LM01–05) → **BM01** → BM02 → BM03/BM04 → TM01/TM02 → WM01–04.

## 6. First slice — BM01 Phase 3→4 bridge (detailed)

**Why first:** most-mechanizable pre-sprint work; ends exactly where the hardened sprint engine begins.

**Precondition:** an approved PRD + architecture (or operator-provided epics input).

**Flow:**
1. `lifecycle-helper run-node B3-epics` → phase-runner spawns an architect/pm child agent running
   `bmad-create-epics-and-stories` with `prd.md` + `architecture.md` as input context → writes `epics/`.
2. **Verify:** `epics_created` (the `epics/` folder parses with the existing `parse-epic` command) **and**
   run `bmad-check-implementation-readiness` → readiness report must pass.
3. **Gate (🧑):** `await-approval --node B3-epics --artifact epics/` — operator reviews the breakdown.
4. **On approve:** hand off to the **existing sprint orchestrator** — which already runs
   `parse-epic → parse-story-range → build-state-doc → per-story loop`. The bridge's output (`epics/`)
   is exactly the sprint engine's input.

**CLI surface (new):** `lifecycle-helper run-node`, `await-approval`, `approve`, `reject`, `status`.
**Acceptance test (CI-able, mocked agent):** given a PRD+arch fixture, the bridge produces a valid
`epics/` the existing `parse-epic` consumes, `check-implementation-readiness` passes, the gate pauses,
and approval yields a sprint-ready epic. (Mirrors `test_orchestration_loop.py` style.)

## 7. Cross-cutting concerns
- **Telemetry:** extend `run_id` correlation to the whole lifecycle (one `run_id` per project run spans
  all nodes); add `LifecyclePhaseStarted/Completed/GatePending/GateApproved/GateRejected` events
  (NEW event types — note M01 ownership of `telemetry_events.py` ⇒ needs a spec waiver or a sibling
  events module).
- **Resume:** `lifecycle-status.yaml` + per-node markers make the long lifecycle resumable (extends the
  existing resume model).
- **Course-correction:** non-linear edges; `reject` and `bmad-correct-course` loop back upstream.
- **Cost/blast-radius:** gates bound spend; complexity scoring picks `bmad-quick-dev` (compresses 2–4)
  for small work vs the full gated lifecycle for large.
- **Both modes:** brownfield inserts `B0-document-project`; greenfield starts at B1/W1.

## 8. Risks & open questions
1. **WDS⇄BMM handoff (highest):** WDS has its own 8-phase methodology, 3 agents, install config, and
   artifact formats. Making WDS scenarios/ux-design/design-system machine-consumable by BMM
   `create-prd`/`create-architecture`/`create-story` needs its own design pass (WM03). Treated as last.
2. **`create-prd` interactivity:** coached discovery run headless loses coaching → draft-with-assumptions
   + gate (resolved by the autonomy decision), but assumption quality is a risk.
3. **Fuzzy-artifact verification:** structural + BMAD-validator checks only; semantic quality stays at
   the human gate. Don't over-promise auto-verification for brief/PRD/architecture.
4. **New telemetry event types vs M01 guardrail** on `telemetry_events.py` — decide: waiver or sibling module.
5. **Three-track concurrency** correctness (the scheduler) — the genuinely new engine logic to get right.

## 9. Guardrails (inherited)
- Reuse the existing engine; do not fork it. No new third-party deps beyond stdlib + `filelock` + `psutil`.
- Conventional Commits + `Generated-By:` trailer. Linux/WSL is the canonical test gate; ruff lint gate.
- Per-milestone branches `bma-d/<slug>`; integrate to a combined branch; push to the fork (no upstream PRs).

## 10. Next steps
1. Operator approves / edits this spec.
2. (Parked) Finish native WSL claude install → Tier-3 real-agent validation of the *current* product.
3. Build **Group F + BM01** first (the macro layer + Phase-3→4 bridge), test-driven, WSL-verified,
   per the superpower-workflow build process.

> **Note (2026-06-17):** Tier-3 real-agent validation is no longer sequenced first — it is *subsumed*
> by full-system validation once the lifecycle automation exists (testing the whole pipeline exercises
> real agents end to end). Cost is not a constraint; the governing objective is that the **final product
> the automation builds is best-in-class, production-ready, engineering-rich, feature-rich, and innovative.**

---

# Part II — Excellence & Innovation Engine (v2, 2026-06-17)

## II.0 Why Part I is not enough (the gap analysis)

Part I makes the orchestrator *drive* every BMAD phase. It does **not** guarantee the OUTPUT is
best-in-class — it leans on BMAD defaults + "tests pass + review passes," which yields software that
*works*, not software that is production-grade. A deep adversarial review of Part I surfaced 14 gaps,
all rooted in one blind spot: **orchestration ≠ excellence.** The fix is an explicit, enforced
Quality & Excellence Engine plus the innovation machinery below.

| # | Gap | Severity | Addressed in |
|---|---|---|---|
| G1 | No explicit, machine-checkable definition of "excellent output" | **critical** | §11 Quality Charter |
| G2 | "Green tests" is gameable — LLMs write weak/tautological tests | **critical** | §12.2 mutation testing |
| G3 | No security engineering pipeline (SAST/deps/secrets/threat model) | **critical** | §13 |
| G4 | Performance/NFRs only *audited* at the gate, not *enforced* per story | high | §12.6 perf budgets |
| G5 | Observability/operability not a first-class output requirement | high | §12.7 |
| G6 | No deployment/release phase — BMAD stops at implementation+retro | high | §16 Phase 6 |
| G7 | Single-pass generation — no excellence-seeking iteration | high | §12.3–.4 self-heal + tournaments |
| G8 | Learning loop unwired — telemetry never steers selection/improvement | high | §15 |
| G9 | No evolving knowledge base / standards injection / cross-run memory | high | §14 |
| G10 | No artifact provenance / reproducibility / run report | medium | §17 |
| G11 | No blast-radius isolation/sandboxing of autonomous agents | high | §18 |
| G12 | No operator experience (DAG dashboard + gate notifications) | medium | §19 |
| G13 | No macro-level failure governance (retries/escalation/quarantine) | medium | §20 |
| G14 | No adversarial red-team validation of the product | medium | §12.8 |

**Central principle of Part II:** the automation must enforce **excellence as deterministically as it
enforces "done."** Every artifact clears an explicit Quality Charter before its gate; the hardest
decisions are won by *competition*, not first-draft; failures *self-heal*; and the system *learns* so
each run is better than the last.

## §11 Product Quality Charter — the definition of "best-in-class"
A versioned, machine-checkable `quality-charter.yaml` the orchestrator enforces on its OUTPUT
(configurable per project; risk-tiered; defaults set a high bar). It is a first-class **input to story
generation** (stories carry their quality requirements) AND to the **release gate**.

| Dimension | Default bar | Enforced by | Lifecycle point |
|---|---|---|---|
| Functional correctness | all ACs met; tests pass | success_verifiers + AC trace | per story |
| Test strength | coverage ≥ threshold; **mutation score ≥ threshold** | coverage + mutation gate | per story |
| Code quality | lint/format clean; type-checked; complexity bound; no dead code | quality gate | per story |
| Security | no high/critical SAST; no vulnerable deps; no secrets; epic threat model | security track §13 | story + epic |
| Performance | meets perf budgets; no regression | perf gate §12.6 | story + release |
| Reliability | error handling, retries, timeouts, graceful degradation | NFR checklist + review | per story |
| Observability | structured logs, metrics, traces, health checks | observability gate §12.7 | per story |
| Accessibility (UI) | WCAG AA | a11y gate (WDS/TEA) | per UI story |
| Documentation | README, API docs, ADRs, runbooks current | docs gate | epic + release |
| Supply chain | SBOM generated; licenses compliant | supply-chain gate §13 | epic + release |
| Maintainability | module size/cohesion/naming; no TODO-debt | review + lint | per story |

**Definition of Done = the in-scope charter dimensions all pass — not "tests green."**

## §12 Quality & Excellence Engine (woven into micro + macro loops)
1. **Escalating Definition-of-Done** — the verifier set is charter-driven, not fixed.
2. **Test-strength validation (anti-gaming)** — add **mutation testing** per story (pluggable per stack:
   mutmut/cosmic-ray, Stryker, etc.); mutation score is a gate. Defeats green-but-meaningless tests —
   the dominant LLM-codegen failure mode. (Critical for "best-in-engineering.")
3. **Self-healing quality loops** — a failed charter gate auto-spawns a fix agent (failure as context,
   triage picks the strategy), re-verifies up to N attempts, then escalates. Output converges to
   excellent rather than stopping at first-attempt-working.
4. **Multi-candidate tournaments + judge panels** — for the **architecture** node and **high-risk
   stories**, generate K diverse candidates, score each with a parallel judge panel against the charter
   + a rubric, synthesize from the winner (graft best ideas from runners-up). Best output for the
   decisions that matter most.
5. **Risk-adaptive verification routing** — the existing complexity/risk score drives *verification
   depth*: high-risk → tournaments + mutation + red-team; trivial → fast path. Spend rigor where it pays.
6. **Performance budgets** — set at architecture, enforced per story via benchmarks; regression blocks.
7. **Observability-as-requirement** — story generation injects observability ACs; a verifier confirms
   logs/metrics/traces/health exist in the output. (The product must be as observable as our orchestrator.)
8. **Red-team stage** — adversarial agents attack each epic's output (security exploits, edge cases,
   chaos/error injection) before the release gate.

## §13 Security & Supply-Chain track (cross-cutting)
| Stage | What | When |
|---|---|---|
| secret-scan | no committed secrets | per story (pre-commit) |
| SAST | static analysis; no high/critical findings | per story |
| dependency-audit | no known-vulnerable dependencies | story + epic |
| threat-model | per-epic STRIDE-style model feeding story requirements | per epic |
| SBOM + license | generate SBOM; license-compliance check | epic + release |
| product secret-mgmt | the product handles its own secrets correctly | review checklist |

## §14 Knowledge & Standards track (persistent; feeds every phase)
The biggest lever for *consistency + quality across a long lifecycle*:
- **Project KB** — coding standards, architecture constraints, stack conventions, domain glossary;
  injected (focused, RAG-style — "load only what's needed") into every child agent.
- **ADR ledger** — architecture decisions recorded and *enforced*; later stories can't silently violate them.
- **Cross-run memory** — Phase-5 retro learnings + drift findings fed **forward** into the next epic/run,
  so each run is better than the last (reuses WDS memory/sync + BMAD project-context).
- **Standards-conformance verifier** — output is checked against the KB.

## §15 Learning & Adaptation engine (close the dormant loop)
The calibration/drift/triage telemetry finally STEERS the system:
- **Calibration-driven selection** — `agents-resolve` consults the per-(model, task-kind) success-rate
  table and prefers the historically-stronger agent/model (safe fallback). *The single biggest
  product-intelligence upgrade.*
- **Risk-adaptive routing** — risk score → verification depth + agent tier.
- **Continuous improvement** — drift flags regressions; the system A/Bs approaches and updates the
  calibration table; retro feeds the KB. The automation gets **measurably better over time** — the
  innovation differentiator.

## §16 Release/Deploy phase (Phase 6) + Maintenance loop
- **B6-release** — scaffold the PRODUCT's CI/CD, semantic versioning, changelog generation, release
  artifacts, deploy, smoke/canary, rollback plan. 🚦 gated by TEA trace + the charter.
- **Maintenance loop** — post-release monitoring hooks + incident runbooks + a feedback edge back into
  Phase 1/2 for the next iteration (ties to WDS phase-8 product-evolution).

## §17 Provenance, reproducibility & run report
- **Artifact provenance ledger** — every artifact records the agent/model/prompt/inputs that produced it
  (extends the hash-chained audit log). End-to-end traceability: requirement→PRD→epic→story→code→test→release.
- **Reproducibility** — pin model/prompt versions per node; a run is re-playable.
- **Run report** — comprehensive end-of-run report: what was built, per-charter quality metrics, cost,
  gates, learnings. Operator-facing *proof of excellence*.

## §18 Execution isolation / blast-radius control
- **Per-story git worktree isolation** (the runtime already understands worktrees) so a bad agent can't
  corrupt the main tree and parallel stories don't collide; merge on green.
- **Optional containerized execution** for stronger sandboxing.
- **Per-node resource/time bounds** (extends the PROBE_TIMEOUT philosophy).

## §19 Operator experience
- **Lifecycle dashboard** — live phase-DAG view: node states, pending gates, per-charter quality metrics,
  cost, provenance (`lifecycle-helper status --dashboard`; optional web view).
- **Gate notifications** — pending 🧑 gates notify via configurable hooks (webhook/Slack/email) so the
  operator isn't polling.

## §20 Macro failure governance
Per-node max-retries + escalation (auto-fix → human); artifact **quarantine + rollback** on repeated
failure; **circuit breakers** (halt a looping phase); partial-failure handling (one story fails → others
continue, reported).

## §21 Extended milestone program (Part II)
**Group Q — Quality & Excellence Engine:** QM01 Charter · QM02 charter-driven DoD/verifiers · QM03
mutation/test-strength gate · QM04 self-healing loop · QM05 tournaments + judge panels · QM06
risk-adaptive routing · QM07 perf budgets + observability gates.
**Group S — Security:** SM01 per-story pipeline (secret/SAST/deps) · SM02 epic threat-model + SBOM/license + red-team.
**Group K — Knowledge & Learning:** KM01 Project KB + standards injection · KM02 ADR ledger + conformance · KM03 cross-run memory · KM04 learning loop (calibration-driven selection + continuous improvement).
**Group R — Release & Operability:** RM01 Phase-6 release/deploy · RM02 provenance + run report · RM03 execution isolation · RM04 dashboard + notifications · RM05 macro failure governance.

**Revised total ≈ 33 milestones** (Part I ~15 + Part II ~18). Large; value-ordered:

1. Part I **Foundation (LM01–05) + BM01** (Phase-3→4 bridge).
2. **Group Q core: QM01–QM04** (charter + escalating DoD + mutation + self-heal) — *sequenced early,
   before climbing to PRD/brief,* because it most directly makes the OUTPUT best-in-class and bolts onto
   the existing, already-hardened sprint verifiers.
3. **KM04 learning loop + QM05 tournaments** — the innovation differentiators.
4. **SM01/SM02 security · QM06/QM07 perf+observability.**
5. **KM01–03 knowledge track · RM01 release phase.**
6. **RM02–05 provenance/isolation/dashboard/governance.**
7. Part I **BM02/BM03 (PRD/brief) · TEA track · WDS track.**

## §22 Revised risks (Part II)
- **Stack-specific tooling** — mutation/SAST/SBOM tools differ per language; the charter + gates must be
  **pluggable/config-driven per stack**, never hardcoded (honors the portability guardrail).
- **Loop/cost safety** — even without a budget cap, self-healing + tournaments need bounded retries +
  circuit breakers so the system can't spin.
- **Charter calibration** — bars must be **risk-tiered + configurable** so trivial work isn't stalled by
  release-grade gates.
- **New external tools vs our no-deps guardrail** — mutation/SAST/etc. are invoked as **subprocesses**
  (the PRODUCT's toolchain), keeping OUR runtime on stdlib + filelock + psutil.
- **Verifier trust** — even mutation + judges aren't perfect oracles for "excellent"; the human gates +
  red-team are the backstop. Don't claim full auto-certification of excellence.

---

# Part III — Integrity, Intent & Innovation (v3, 2026-06-17)

## III.0 The deeper blind spot: Goodhart's Law
Part II makes excellence into **metrics-as-gates**. Autonomous agents optimize to *pass the gate*, not
to *achieve the goal* (reward hacking / Goodhart's Law). Left unguarded: agents weaken tests to beat
mutation, satisfy the *letter* of ACs, and — worst — the **self-healing loop becomes a gaming amplifier**
("make the gate green" → lower the bar). v2's engine therefore needs an **integrity layer** that makes
the gates *un-gameable*, defends *intent* (garbage-in defeats output excellence), keeps the human gate a
*real decision*, counters *over-engineering*, and proves the automation is *actually* excellent.

Fresh gaps from lenses not used in Parts I–II:

| # | Gap | Tier | §|
|---|---|---|---|
| H1 | Quality gates are gameable (Goodhart); self-heal can lower the bar | **CRITICAL** | §23 |
| H2 | Output excellence engineered, but INTENT (PRD/epic/AC) quality is not — garbage-in | **CRITICAL** | §24 |
| H3 | Human gate can degrade to rubber-stamp (no decision-support) | **HIGH** | §25 |
| H4 | No cross-artifact consistency / change-propagation within a run | **HIGH** | §26 |
| H5 | Learning loop is exploit-only + cold-start-blind; judges unvalidated; model drift silent | **HIGH** | §27 |
| H6 | No simplicity counterweight → "feature-rich" becomes over-engineered bloat | **HIGH** | §28 |
| H7 | Builds what's asked, but no engine for *innovative/feature-rich beyond* the spec | MED-HIGH | §29 |
| H8 | No way to KNOW the automation produces excellence (judges unaudited) | MED-HIGH | §30 |
| H9 | Generated-code license/IP + regulatory compliance ungoverned | TIERED | §31 |
| H10 | Single-codebase assumption; no multi-component/infra/data/contract topology | TIERED | §32 |

## §23 Integrity layer — Goodhart-resistance & anti-gaming (CRITICAL)
- **Held-out / rotating verification** — agents never see the exact gate they're scored on; a rotating,
  held-out verification set (and fresh-context judges) prevents train-to-the-test.
- **Semantic validation beyond metrics** — judges check the *goal* is met (does it actually do the
  thing?), not just that numbers passed; metric-up-but-goal-flat is a fail.
- **Self-heal anti-gaming (critical)** — the self-healing loop **may not lower the bar**: any fix diff
  that *reduces* coverage, deletes/weakens assertions, narrows scope, or relaxes a charter threshold is
  auto-rejected. The loop can only raise quality, never the gate.
- **Test-strength that's hard to game** — property-based + metamorphic tests alongside example tests;
  mutation testing *of the tests' own assertions*; "do the tests still fail when the code is broken?"
- **Judge integrity** — diverse, fresh-context judge panels; surface dissent (not just majority);
  periodic **human audit** of judge verdicts; track judge accuracy and retire bad judges.
- **Goodhart monitors** — watch for "all green but quality flat/declining" signals and trip a human review.

## §24 Intent & Requirements quality — garbage-in defense (CRITICAL)
- **Intent Charter** (parallel to the Quality Charter, governing PRD/epics/stories): every requirement
  must be **unambiguous, complete, testable, consistent, traceable**.
- **Requirements gates** — ambiguity detection, completeness check, conflict detection across
  PRD↔epics↔stories, and **AC quality** (every acceptance criterion measurable + verifiable).
- **Definition-of-Ready (DoR)** — a story can't enter the sprint until it's *ready* (clear, estimable,
  testable, deps resolved). DoR (before) complements DoD (after) — prevents excellent code solving an
  under-specified problem.

## §25 Gate decision-support — anti-rubber-stamp (HIGH)
Every 🧑 gate presents an **Approval Packet**, not a raw artifact: what changed (diff), the **assumption
ledger** (every assumption the agent made, flagged for validation), risks, **quality-metric deltas**, the
specific **open questions requiring human judgment**, and a recommended decision + confidence. Supports
batch/async approval and reject-with-notes → targeted course-correct. Without this, gated-autonomy decays
into rubber-stamping and the whole safety model fails.

## §26 Cross-artifact consistency & change propagation (HIGH)
- **Bidirectional traceability enforced continuously** (PRD↔arch↔epic↔story↔code↔test), not only TEA's
  test↔req: does the code still satisfy the PRD? was an ADR/architecture constraint violated during impl?
- **Change-impact analysis** — a course-correct (PRD/arch change) computes the downstream blast radius
  and re-opens/regenerates + re-verifies only the affected nodes (not a full redo).

## §27 Learning-loop maturity — make it work + innovative (HIGH)
- **Explore/exploit policy (bandit-style)** — mostly exploit the best-calibrated agent/model, but
  *explore* alternatives to *discover* better ones. Pure exploitation can never improve; this lets the
  system get genuinely better, not just repeat. (The real innovation in the learning loop.)
- **Cold-start bootstrapping** — seed calibration from priors / shared cross-project history;
  exploration-heavy until data accrues.
- **Judge calibration** — periodic human-eval scores *calibrate the automated judges* (the judges are
  validated, not trusted blindly) — ties to §30.
- **Model-version canary** — on a model/prompt change, canary + compare output quality before adopting;
  guards against silent regression when the underlying model updates.
- **Non-determinism handling** — flake detection + quorum verification for non-deterministic gates.

## §28 Simplicity & anti-over-engineering — the YAGNI counterweight (HIGH)
"Feature-rich + best-engineering" without a counterweight produces **over-engineered bloat**. Add an
explicit **simplicity gate**: "is this the simplest design that meets the charter?" — penalize unneeded
abstraction, speculative generality, and dependency sprawl; enforce complexity + dependency budgets; run
the `/simplify` ethos as a pipeline stage. **This also guards the spec/automation itself from bloating —
we must eat our own dog food and tier aggressively (see §33).**

## §29 Innovation & feature-richness engine — serve "feature-rich, innovative" (MED-HIGH; opt-in)
- **Gated feature-ideation** — an agent proposes enhancements *beyond the literal requirements* (delight,
  competitive parity, edge-case UX, smart defaults), human-gated into the backlog. Turns "correct" into
  "exceptional."
- **Competitive/market enrichment** — wire BMAD `market-research` into feature discovery.
- **UX-delight pass** — microcopy, empty/error/loading states, perceived-performance UX (beyond WDS structure).
- *Opt-in per project* — some products want minimal, not maximal; innovation must be a dial, not a default
  (and is itself subject to the §28 simplicity gate).

## §30 Automation self-evaluation — how we KNOW it's excellent (MED-HIGH)
- **Reference-project benchmark corpus** — run the automation on known projects, score the output per the
  charter, and track across automation releases (the automation's OWN regression suite; extends
  golden-trace from the sprint to the whole lifecycle).
- **Output-excellence human-eval rubric** — periodic human scoring of produced products → calibrates the
  automated judges (§27) and reports the automation's *own* quality trend over time.

## §31 Compliance, license & IP hygiene (TIERED — by product/domain)
Generated-code **license/IP scan** (LLMs can emit license-incompatible code); **regulatory compliance**
track (GDPR/HIPAA/SOC2/a11y-law, config-driven per domain); audit/compliance reporting. *Enable for
regulated/commercial products; off for prototypes.*

## §32 Topology & scale (TIERED — by project shape)
Multi-component/monorepo orchestration (a DAG per component + cross-component **contract testing**, Pact);
**infrastructure-as-code** phase + environment provisioning; **data track** (schema design, migrations,
data quality). *Enable for multi-service/infra-heavy products; off for single-codebase.*

## §33 Milestone deltas — woven, not bolted (discipline: avoid spec bloat)
The CRITICAL/HIGH items **fold into existing early groups** (they're integral, not a new tail):
- **Group Q gains:** QM08 integrity/anti-gaming layer (§23) · QM09 simplicity gate (§28) — these are part
  of the *excellence core*, built alongside QM01–04.
- **LM04 (approval gate) gains:** gate decision-support / Approval Packets (§25).
- **Group B (PRD/epics) gains:** intent-quality gates + Definition-of-Ready (§24).
- **Learning gains:** KM05 explore/exploit + cold-start + judge calibration + model canary (§27).
- **New small group CM:** cross-artifact consistency + change propagation (§26).
- **MED-HIGH new:** IM innovation/feature-ideation (§29, opt-in) · EM automation self-eval/benchmark (§30).
- **TIERED tracks (on demand):** compliance (§31), topology/scale (§32).

**Revised core program ≈ 38 milestones;** tiered tracks add on demand. **Build-order change:** §23
integrity + §28 simplicity join **Group Q core** (you cannot ship a trustworthy excellence engine without
anti-gaming + simplicity), and §24 intent-quality + §25 gate-decision-support join the **Foundation/PRD**
work (they protect the inputs and the human gates from day one).

## §34 Disciplined closing note
The integrity layer (§23) is the single most important addition in this pass — it protects the *entire*
excellence engine from being gamed; everything in Part II is only as trustworthy as §23 makes it. Intent
quality (§24) and gate decision-support (§25) protect the two ends (inputs, human judgment) the metrics
can't. With these, the spec is **mature** — further review passes hit diminishing returns. Two standing
disciplines going forward: (1) **tier aggressively** — build the core (Foundation + BM01 + Group Q incl.
integrity & simplicity), prove output excellence on real stories, then expand; (2) **the automation must
obey its own §28 simplicity gate** — resist gold-plating the orchestrator itself. Recommended next action:
lock the spec and build the core.

---

# Part IV — Comprehensive Verification Taxonomy (v4, 2026-06-17)

## IV.0 Why this part exists
The Quality Charter (§11) named *dimensions* (test-strength, security, perf…) but not the **complete set
of test types, bug classes, and vulnerability classes** behind each. For "production-readiness from day
one," verification must be **exhaustive for what applies** — nothing relevant is optional at the
production tier. The catch: applicability is **stack/product-conditional** (don't run cross-browser tests
on a CLI; don't run memory-safety fuzzing on pure Python; DO run prompt-injection tests if the product
embeds an LLM). So:

**Production-from-day-one principle:** at the architecture node the orchestrator resolves a **Product
Verification Profile** (web-app / API-service / CLI / library / mobile / data-pipeline / embeds-AI /
infra/IaC / desktop …). The profile **activates the full applicable taxonomy** below in the charter;
irrelevant categories are auto-excluded; risk-tiering controls *per-story depth*, but the **product as a
whole must clear the entire applicable taxonomy before the release gate.** All tools are pluggable
per-stack subprocesses (keeps our runtime dependency-free).

## §35 Test-type matrix (comprehensive)
Cadence: S=per story · E=per epic · R=release gate. "Applies" = profile condition.

| Category | Types | Technique / tool class | Cadence | Applies |
|---|---|---|---|---|
| **Functional** | unit, integration, component, **system**, end-to-end | xUnit, test runners, Playwright/Cypress | S/E/R | all |
| **API/contract** | API schema, **consumer-driven contract** (Pact), backward-compat | schemathesis, Pact, OpenAPI diff | E/R | services |
| **Hygiene** | smoke, sanity, **regression** (full suite gate) | CI re-run | S/E/R | all |
| **Test-strength** | **property-based**, **metamorphic**, **mutation**, combinatorial/pairwise, boundary/equivalence, **negative/error-path** | Hypothesis/fast-check, mutmut/Stryker, pict | S | all |
| **Fuzzing** | coverage-guided **fuzz**, input/grammar fuzz, API fuzz | libFuzzer/atheris/restler | E/R | parsers, APIs, untrusted input |
| **Performance** | micro-benchmark, **load**, **stress**, **spike**, **soak/endurance**, **volume**, scalability | k6/Locust/JMH, profilers | E/R | services, perf-sensitive |
| **Resource** | **memory-leak**, handle/connection-leak, allocation profiling | valgrind/leak-sanitizers/profilers | E/R | long-running, native |
| **Resilience** | **chaos/fault-injection**, **failover/recovery**, disaster-recovery, **idempotency**, **concurrency/race/deadlock** | chaos tools, race detectors (tsan), jepsen-style | E/R | distributed, stateful, concurrent |
| **Security (active)** | **SAST**, **DAST**, IAST, **SCA/dep-audit**, **secret-scan**, **security fuzz**, **pentest/red-team**, **IaC scan**, **container/image scan**, **license/IP scan** | semgrep/codeql, ZAP/Burp, trivy/grype, gitleaks, tfsec/checkov | S/E/R | per profile (see §37) |
| **UI/UX** | **cross-browser**, **responsive/cross-device**, **visual-regression**, snapshot, **accessibility (WCAG AA)**, usability | Playwright multi-engine, Percy/Chromatic, axe | S/E/R | web/mobile UI |
| **Data** | DB integrity, **migration up/down**, data-quality, backup/restore | migration test harness, great-expectations | E/R | data/DB-backed |
| **Compatibility** | cross-OS/platform, **backward/forward compat**, **upgrade/downgrade** | matrix CI | E/R | distributed/installed |
| **i18n/l10n** | locale, RTL, encoding, timezone/DST | pseudo-localization | E/R | localized products |
| **Install/Deploy** | installability, config, deploy smoke, **canary**, rollback | smoke harness | R | shipped products |

## §36 Bug-class hunt list (what review + tests must actively target)
Generic "review the code" misses classes. Each story's review + test-design explicitly hunts (profile-
gated): logic/functional · boundary/off-by-one · null/undefined/type · **concurrency: races, deadlocks,
livelocks, TOCTOU, atomicity, ordering/eventual-consistency** · **memory: leak, use-after-free, overflow**
(unsafe langs) · **resource leaks: file handles, sockets, connections, threads** · error-handling:
swallowed errors, wrong recovery, **info-leak via errors** · **state/cache consistency, stale reads** ·
integration/interface mismatch · performance: **N+1, hot-path, unbounded allocation, sync-in-async** ·
configuration/env · **time/timezone/DST/locale** · floating-point/precision · regression · input-
validation/edge-case · resource exhaustion/unbounded growth. (This list is injected into the review +
TEA test-design prompts so detection is *targeted*, not hopeful.)

## §37 Vulnerability taxonomy (explicit; mapped to technique + cadence)
| Class | Examples | Technique | Cadence | Applies |
|---|---|---|---|---|
| **OWASP Web Top 10** | broken access control, crypto failures, **injection (SQLi/XSS/cmd)**, insecure design, **misconfig**, vulnerable components, authn failures, integrity failures, logging/monitoring failures, **SSRF** | SAST + DAST + threat-model | S/E/R | web/services |
| **OWASP API Top 10** | **BOLA**, broken authn, broken object-property auth, resource consumption, mass-assignment | DAST/API-fuzz + review | E/R | APIs |
| **OWASP LLM Top 10** | **prompt injection**, insecure output handling, model DoS, sensitive-info disclosure, excessive agency | LLM red-team + guardrail tests | E/R | embeds AI/LLM |
| **CWE (beyond SAST)** | **path traversal**, **insecure deserialization**, **crypto misuse/weak randomness**, XXE, race/TOCTOU, integer overflow | SAST + manual + fuzz | S/E | per language |
| **Memory safety** | buffer overflow, UAF, OOB read/write | sanitizers + fuzz | E/R | C/C++/unsafe Rust |
| **Supply chain** | vulnerable/typosquatted/malicious deps, **SBOM**, license incompat, **LLM-emitted license-incompatible code** | SCA + SBOM + license scan | S/E/R | all |
| **Secrets** | committed secrets, hardcoded creds, weak key mgmt | secret-scan + review | S | all |
| **IaC / Cloud / Container** | misconfigured cloud resources, over-broad IAM, public buckets, vulnerable base images | tfsec/checkov, trivy image scan | E/R | infra/containerized |
| **Privacy / Data protection** | PII exposure, missing encryption-at-rest/in-transit, retention, **GDPR/CCPA/HIPAA** | data-flow analysis + compliance checklist | E/R | handles personal data |

## §38 Day-one enforcement model
1. **Profile resolution** (architecture node) → selects applicable rows from §35–§37.
2. **Charter activation** → the selected verification set becomes mandatory charter dimensions.
3. **Per-story:** risk-tiered slice (fast path for trivial; full strength for high-risk) — but every
   story still passes its profile-mandatory security + test-strength gates.
4. **Per-epic:** threat-model, fuzz, perf battery, resilience, SBOM, red-team.
5. **Release gate (R):** the **entire applicable taxonomy must be green** — TEA `trace` consumes the full
   coverage matrix; a gap in any profile-mandatory category = **FAIL, no release.** This is what
   "production-ready from day one" means operationally: the product cannot ship until the complete
   applicable test/bug/vuln set passes.
6. **Anti-gaming (§23) applies to all of it** — held-out checks + semantic validation so the battery
   can't be satisfied with hollow tests.

## §39 Milestone impact (folded, profile-gated)
- **Group Q:** QM03 expands to the **full §35 test-type matrix** (driver per category, pluggable tools);
  QM11 **bug-class-targeted review/test-design** (§36 injected into prompts).
- **Group S (security) expands** to the full §37 taxonomy: **SM03** DAST + security-fuzz + pentest/red-team;
  **SM04** IaC + container/cloud scanning; **SM05** API + **LLM** security (conditional); **SM06** crypto +
  privacy/PII + license-of-generated-code.
- **New:** **PM-profile** — the Product Verification Profile resolver at the architecture node (drives
  which rows activate).
- Core program now ≈ **42 milestones**; the security/test tracks are the heaviest but profile-gated so a
  CLI/library project runs a small applicable subset while a regulated web service runs the full battery.

## §40 Honest closing on completeness
With Part IV the spec is **complete on the verification axis** — it now enumerates the full applicable
test, bug, and vulnerability taxonomy and enforces it as a release gate, while staying sane via
profile-conditioning + risk-tiering. Two caveats kept honest: (1) **completeness ≠ infallibility** — no
battery catches every bug; the human gates + red-team + production monitoring (§16 maintenance loop) are
the backstop. (2) Tools are **stack-specific and evolve** — the taxonomy is the contract; the specific
tools are pluggable config, not hardcoded. The spec is now mature across product-excellence *and*
verification-completeness; recommended action remains: build the core (now incl. the profile resolver +
the security/test-strength gates from day one).
