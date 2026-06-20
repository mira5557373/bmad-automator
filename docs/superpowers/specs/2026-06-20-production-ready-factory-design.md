# Production-Ready Factory — Design Spec

> Date: 2026-06-20 · Status: **Draft for review** · Topic: turn `bmad-story-automator` into a factory whose outputs are production-ready from day one.
> Validation provenance: design adversarially reviewed across four lenses — BMAD-method compatibility, TEA compatibility, factory-integration feasibility (against the real `story_automator` code), and a best-in-market completeness critique. Grounded in `external/BMAD-METHOD` (v6.8.0) and `external/bmad-method-test-architecture-enterprise` (v1.19.0).

## 1. Goal

Make the automation system a **production-ready factory**: every product it builds (or extends) must be production-ready, feature-complete, observable, vulnerability-free, and best-in-class in engineering — *from the first commit*. The first target product (Profile #1) is an **MSME SaaS ERP** (headless Odoo CE 19 + FastAPI gateway + Next.js BFF + agentic SGE layer + K8s), whose own production bar is the seven AND-ed **Hard Rule 6** criteria.

## 2. Core insight (the gap being closed)

`bmad-story-automator` faithfully drives BMAD's **build loop** (`create-story → dev-story → automate → code-review → retrospective`) with strong *orchestration-plane* engineering (state machine, policy snapshots, HMAC audit, telemetry, drift, budgets, trust-but-verify). But BMAD's **production-readiness machinery is optional and not wired in**: the teeth (risk gates, requirements traceability, test-quality scoring, NFR-evidence, deterministic PASS/CONCERNS/FAIL/WAIVED gates, burn-in) live in the **TEA module** and are not invoked.

Today "done" = *"expected files exist + sprint-status says done + critical review issues cleared"* (`success_verifiers.py`) — an **orchestration** check, not a **product-quality** gate. This spec installs the missing QA stations.

## 3. Decisions captured

| Decision | Choice |
|---|---|
| Scope | Design the full program; implement the **keystone (code-altitude) gate first**. |
| Product type | Web / full-stack (here: enterprise agentic ERP). |
| Enforcement | **Auto-remediate, then escalate.** FAIL → bounded fix loop; CONCERNS → proceed + logged mitigation; WAIVED → operator-only. |
| Stack model | **Opinionated golden stack**, expressed as a versioned **Product Profile**. |
| Gate approach | **Hybrid C** — BMAD/TEA LLM agents *generate*; a deterministic Python *Adjudicator* renders the verdict. LLM proposes; tools + code dispose. |
| Factory model | **General factory + Product Profile.** MSME ERP = Profile #1. |
| Gate altitude | **Two tiers** (code + system); build code-altitude first. |

## 4. Architecture — four tiers, profile-driven

```
CONTROL PLANE — existing orchestrator (state.md, sprint-status, policy snapshot,
telemetry/audit, escalation ceilings) — now consults the GATE for "done"
        │
  TIER 1 GENERATORS (LLM, BMAD/TEA via tmux)
        │  risk/test-design · atdd · dev-story · automate · code-review
        ▼
  TIER 2 EVIDENCE COLLECTORS (subprocess, product toolchain → normalized JSON)
        │  tests · coverage · traceability · static · security · license · compliance
        │  perf · a11y · otel-wiring · invariants · agentic · supply-chain · mutation
        ▼
  TIER 3 ADJUDICATOR (pure Python: verdict = f(risk_profile, evidence[], thresholds))
        │  per-category + overall PASS / CONCERNS / FAIL / WAIVED → gate file + events
        ▼
  TIER 4 REMEDIATOR (LLM, bounded)  ── BMAD review_continuation → dev-story
```

- **LLM generates; code decides.** No LLM ever writes the verdict → ungameable.
- **Tier 3 is a pure function** of persisted inputs → replayable (reuses M10 golden-trace).
- **Additive on the existing codebase** (~2,500 LOC across ~12 small modules + tests), not a rewrite.

## 5. Product Profile

A versioned, layered bundle (loads like `runtime_policy`: bundled → project → env) that specializes the general factory per product:

```yaml
id: msme-erp
seed_template: { ref: msme-erp-golden-template@1.x }   # FACTORY-OWNED bundle (not TEA-provided);
                                                       # delivered by a post-M19 seed-template milestone.
                                                       # TEA fragments (network-first.md, selector-resilience.md,
                                                       # data-factories.md, pact-*.md, network-recorder.md) are
                                                       # the reference implementations the bundle instantiates.
toolchain: { python: [ruff,mypy,pytest,...], ts: [biome,vitest,playwright], iac: [opentofu,trivy,...] }
matrix:    { P0:{coverage_pct:100, levels:[unit,integration,contract,e2e]}, P1:{coverage_pct:90,...} }
categories: { code: [...], system: [...] }   # see §6
rules:     { security:{sast_max_high:0, deps_max_critical:0}, license:{forbidden:[BSL,SSPL], boundary:{agpl:[odoo-pod]}} }
cost_tier: { sku_id: "msme-starter", arpu_monthly: 0, max_pod_cost_per_tenant: 0 }   # placeholder until DG-2;
                                                                                     # zero values + DG-2 in forbidden_until
                                                                                     # cap cost_to_serve at CONCERNS, not FAIL.
invariants: registry: invariants.yaml         # the DG/ADR → check mapping (§6.4)
forbidden_until: { "ADR-0083": ["E*.envelope-*"],
                   "DG-2":     ["*.cost-to-serve"] }   # block stories depending on open ADRs / undefined DGs
```

The Profile's invariants reach the generation agents via BMAD's **`customize.toml` 3-layer merge + `persistent_facts` + activation prepend/append** — no fork of BMAD.

## 6. The Adjudicator

### 6.1 Risk drives requirements; code checks them
Risk Generator (TEA `*risk`) emits a structured risk profile (`Probability×Impact = 1–9`, category ∈ TECH/SEC/PERF/DATA/BUS/OPS). The engine maps risk → priority (P0–P3) → *required* coverage/levels/NFRs, then deterministically compares *actual* evidence to *required*. **Risk is LLM/human-proposed; every threshold check is code.**

### 6.2 Code-altitude categories

| Category | PASS rule (profile defaults) | Evidence |
|---|---|---|
| correctness | all tiers green, 0 regressions, line/branch ≥ risk-required | pytest, vitest, playwright, coverage |
| traceability | P0 ACs 100% / P1 ≥90% mapped to tests | TEA `e2e-trace-summary.json` (fallback: GWT title parse) |
| test_quality | TEA `test-review` ≥ band; 0 flaky over burn-in N×; no hard-waits | TEA test-review, burn-in runner |
| **mutation** | mutation score ≥ threshold on changed code (sampled/budgeted) | mutmut / Stryker |
| static/type | tsc=0, mypy=0, ruff/Biome=0, deadcode ≤ budget | tsc, mypy, ruff, Biome, knip |
| security | SAST 0 high+, deps 0 critical-unwaived, 0 secrets | semgrep, trivy, osv, gitleaks |
| compliance | DPDPA PII-redaction + residency client + audit-envelope + consent-receipt present & correct | compliance rulepack (semgrep/conftest) |
| license (HR-2) | 0 forbidden licenses + boundary-aware (AGPL only in Odoo pod) | syft-license + boundary lint |
| **supply_chain** | SBOM emitted, deps signed/pinned, provenance present | Syft, Cosign verify, Trivy |
| **api_compat** | no breaking REST/schema change; audit-log additive-only | openapi-diff, schema-diff |
| **migrations** | Alembic/Marabunta dry-run clean + reversible + advisory-lock correct | migration harness |
| performance | bundle/Lighthouse budgets met; no static N+1/unbounded | Lighthouse-CI, bundlesize, perf lints |
| accessibility | axe 0 serious/critical on changed UI | @axe-core/playwright |
| observability | OTel traces/metrics/logs wired; `/healthz`+`/readyz`; SLO declared | otel-wiring, probe check |
| invariants (DG/ADR) | checkable DG/ADR rules pass (incl. **DG-12** envelope emitted, **DG-13** no direct `httpx` to Odoo, **DG-14** no SUDO + agent-bound `res.users`, **DG-34** no direct LLM calls, residency client present) | invariant registry → semgrep/conftest |
| agentic *(if touched)* | (a) **pack-schema v1.2**: per tool envelope fields `{risk_tier, reversibility_class, time_lock, autonomy}` present + valid (JSON-schema or semgrep at collect time); (b) **AIBOM diff**: every new/changed tool has a CycloneDX-1.6 + SPDX-AI-3.0 entry (FAIL if missing); (c) **OPA constitution**: `opa compile` exit=0 AND `opa test` green when test rules exist; (d) evals ≥ threshold; (e) guardrail coverage; (f) per-action SGE envelope emitted with governance triple `agent_version + opa_bundle_hash + constitution_version` (DG-25) | DeepEval/Promptfoo/RAGAS, `opa compile`/`opa test`, pack-schema validator, AIBOM differ |
| **docs** | docs site builds; API docs generated; **runbook present** (`docs/operations/gate-troubleshooting.md` referenced as a gate-checked artifact — see §11.1) | docusaurus build, presence checks |
| process/DoD | ADR Production-Readiness section present; ACs↔tasks↔tests traced; File List complete | adr-prod-readiness, trace parser |

### 6.3 Verdict aggregation (deterministic)
```
required = risk_to_requirements(risk_profile, profile.matrix)
per category: verdict = profile.rules[cat](evidence, required)   # PASS/CONCERNS/FAIL/NA
collector status == error → fail-closed (never silent PASS)
if any risk.score==9 and no mitigation        → FAIL
elif any category == FAIL                       → FAIL
elif any category == CONCERNS                   → CONCERNS   # proceeds + logged mitigation debt
else                                            → PASS
# WAIVED: only a signed, unexpired operator waiver covering the exact failing categories
```

### 6.4 Schemas (compact)
- **Evidence record** (the only thing the Adjudicator reads — never raw tool output): `{collector,tool,tool_version,category,tier,status(ok|violation|error),metrics,findings,raw_output_ref,exit_code,duration_ms,deterministic}`. LLM evidence uses the same shape + `confidence`+`rationale`; confidence `<5` forces CONCERNS/needs-human (TEA confidence gate). LLM evidence is *persisted*, so adjudication stays replayable even though generation isn't.
- **Gate file** (persisted, auditable): `gate_id(UUIDv7), target{kind,id,epic}, tier, commit_sha, scanner_data_snapshot, profile{id,version,hash}, risk_profile_ref, categories{verdict,required,actual,evidence,rationale}, overall, waivers[], evidence_bundle_hash`. Hash-chained into the existing audit log.
- **Invariant registry** (`invariants.yaml`): per DG/ADR `{id, checkable:yes|no, check_type:semgrep|conftest|presence|human, rule_file, severity}`; encodes `ADRs > corrections > vision` precedence; non-checkable ones become LLM-reviewer/human checklist items. Concrete entries for MSME:
  - `{id: DG-12, checkable: yes, check_type: semgrep, rule_file: semgrep/dg12_envelope_emitted.yml,    severity: FAIL}`
  - `{id: DG-13, checkable: yes, check_type: semgrep, rule_file: semgrep/dg13_no_direct_httpx_odoo.yml, severity: FAIL}`
  - `{id: DG-14, checkable: yes, check_type: semgrep, rule_file: semgrep/dg14_no_sudo_tenant_binding.yml, severity: FAIL}` — matches `sudo()` / `with_user()` / `env(user=...)` in `msme_odoo_adapter` lacking explicit `(tenant, agent_id)` context filter
  - `{id: DG-25, checkable: yes, check_type: semgrep, rule_file: semgrep/dg25_governance_triple.yml,    severity: FAIL}` — envelope construction must include all three triple fields
  - `{id: DG-34, checkable: yes, check_type: semgrep, rule_file: semgrep/dg34_no_direct_llm.yml,        severity: FAIL}`
  - Residency: `{id: DG-4-L1, checkable: yes, check_type: semgrep, rule_file: semgrep/dg4_residency_client.yml, severity: FAIL}`
  M18's `agentic`/`invariants` rule functions treat any FAIL-severity invariant violation as a **hard FAIL** with no CONCERNS path.

- **`cost_tier`** (per-profile): `{sku_id: str, arpu_monthly: number, max_pod_cost_per_tenant: number}`. The MSME profile ships with zeros + `DG-2` in `forbidden_until` so the system-altitude `cost_to_serve` collector renders CONCERNS (not FAIL) until DG-2 SKU is defined; once defined, the cost rule becomes `k6_mean_pod_resources × regional_price ≤ max_pod_cost_per_tenant`.

## 7. Evidence integrity & trust boundary (the property that makes "ungameable" true)

- Collectors run **in the product's container, on a fresh checkout @SHA, invoked by the orchestrator host** — **never** by the generation child (which runs `--dangerously-skip-permissions` and otherwise could forge a PASS; closes audit F-010/F-011 for the gate's purposes).
- Evidence + gate files are written outside the child's tmux working tree and hash-chained into audit.
- The child's self-reports are **unverified hints, never evidence** (BMAD "Blind Hunter" principle).
- **Fail-closed**: a collector that errors ⇒ CONCERNS (non-critical) or block (required category unevaluable) — mirrors the product's ClamAV "do not fail-open" rule.
- **Replay vs re-evaluation**: gate file records the scanner-data snapshot. Same inputs → same verdict (audit); new CVE/rule data → re-eval may legitimately differ.

## 8. Capability modules

| # | Module | Orchestrates (BMAD/TEA) | Feeds |
|---|---|---|---|
| 1 | Risk-scored readiness (pre-build) | Implementation-Readiness Check (epic) + `validate-create-story` (story) + TEA `*risk`/`test-design`; computes story↔ADR deps → `forbidden_until` | risk_profile, thresholds; blocks `ready-for-dev` |
| 2 | Test-first + DoD | TEA `atdd` (verify RED) → BMAD `dev-story` TDD → DoD verifier | correctness, traceability, test_quality |
| 3 | Security & license & supply-chain | semgrep/trivy/osv/gitleaks + syft boundary-aware license + Cosign/SBOM + DG/ADR security invariants | security, license, compliance, supply_chain, invariants |
| 4 | Observability-by-default | seed template ships OTel+SLO+health; gate verifies presence | observability |
| 5 | Burn-in + flaky + mutation + CI governance | burn-in N×, mutation sampling, ban hard-waits, selective exec, emit Tekton CI | test_quality, correctness, mutation |
| 6 | Factory self-trust (foundation) | the 71-finding audit backlog + the §7 trust boundary + sandbox the generation child | the gate's own validity |

Agentic-product quality is woven through modules 2–3 and the `agentic` category. Product-quality patterns from TEA (network-first, selector-resilience, data-factories, HAR, three-step fixtures) are pre-wired in the seed template and enforced via `test_quality`; consumer-driven contract tests (Pact) are a required test level under `correctness`/`traceability` for changed service boundaries.

## 9. Orchestrator integration

### 9.1 Per-story step map (BMAD-native states in **bold**)
```
EPIC ► sprint-planning + Implementation-Readiness Check ► [story loop] ► per-epic SYSTEM GATE + retrospective ► next epic
STORY LOOP (each step = fresh tmux child):
 READINESS  1 create-story  2 validate-create-story  3 risk+test-design(TEA)
            ▸ readiness gate PASS + no OPEN blocking ADR → ready-for-dev
 BUILD      4 atdd(verify RED)  5 dev-story(TDD,DoD) → in-progress  6 automate(cond.)  7 code-review → review (=evidence)
 GATE       8 trust-boundary checkout@SHA → collectors → evidence[] → verdict
            PASS→commit+done · CONCERNS→commit+mitigation-debt+done · FAIL→Remediator · WAIVED→operator-only
            exhausted/risk-9 persists → PARK+escalate, advance to next DAG-independent story (no deadlock)
```
`code-review` becomes an **evidence source** for the gate; the gate is the single authority for `review → done`. The factory creates stories directly in `backlog` / `ready-for-dev`; legacy stories already in the BMAD-v4 `drafted` state are auto-mapped to `ready-for-dev` by `bmad-sprint-status`, so the gate accepts entry from any recognized state.

### 9.2 Control flow
- **Resumable**: gate file keyed to `commit_sha`; reused if SHA unchanged, re-run otherwise.
- **CONCERNS** emits a tracked **mitigation-debt** annotation (cleared by operator/retro); profile may mark some categories' CONCERNS as blocking (e.g. security).
- **FAIL → Remediator** reuses `review_max_cycles`/`crash_max_retries`; writes `[AI-Review]` tasks → fresh `dev-story` via `review_continuation`, honoring dev-story **edit-authorization** (only Tasks/Subtasks, Dev Agent Record, File List, Change Log, Status, `baseline_commit`).
- **PARK + continue**: on exhaustion/persistent risk-9 → park + escalate (telemetry+audit) and advance to the next independent story via the epic DAG; optionally invoke `bmad-correct-course` to re-plan. The run never deadlocks on a sleeping operator.
- **Human takeover**: all writes are BMAD-native (sprint-status + story file), so `bmad-help` stays consistent if a human steps in. The factory drives the gate; `bmad-help` is not relied upon for the gate step.

## 10. System-altitude gate (per-epic / release — milestone M22)

Ephemeral environment, tiered: **minimal** (changed service + deps via testcontainers/compose) for most epics; **full** (`kind`/`k3d` + Helm of changed services + CNPG/Valkey/Kafka/Temporal, seeded) for infra/cross-cutting epics + release candidates.

| Check | Harness | Hard Rule 6 |
|---|---|---|
| Reliability (RTO/RPO/SLA) | CNPG failover + pgBackRest restore timing | (a) |
| Resilience | Chaos Mesh pod-kill / net-loss / IO-fault | (b) |
| Durable HITL | start approval → kill pod → assert Temporal Signal survived | (c) |
| Blast radius | load tenant A → assert tenant B SLO unaffected | (d) |
| Cost-to-serve | k6 load → resource×price; CONCERNS if ARPU/DG-2 undefined | (f) |

Plus progressive-delivery/rollback evidence (Argo Rollouts blue-green/canary). Epic-gate FAIL can reopen specific stories or spawn remediation stories.

## 11. BMAD compatibility

- Loop, skills, and `sprint-status` states map to v6 (`create-story`/`validate-create-story`/`dev-story`/`code-review`/`sprint-planning`/`retrospective`/`bmad-help`).
- Honors dev-story **edit-authorization** and the `code-review → review_continuation → [AI-Review]` loop.
- Leverages `project-context.md` (conformance), `customize.toml`/`persistent_facts`/activation hooks (invariant injection), Implementation-Readiness Check (epic gate), `correct-course` (re-plan), `checkpoint-preview` (HITL).
- **Graceful degradation**: if TEA is absent, native collectors still run; traceability falls back to GWT title parsing.

### 11.1 Operator runbook (gate-checked)

`docs/operations/gate-troubleshooting.md` (owned by M19) is a first-class artifact the gate's `docs` category verifies present and non-empty. Required sections:

1. **Verdict interpretation decision tree** — per-category PASS/CONCERNS/FAIL with the next action.
2. **Remediation-loop exhaustion flow** — `review_max_cycles` exceeded → PARK + escalate; `state.run_id` checkpoint; how to resume.
3. **Partial-FAIL playbook** — when to spawn per-category remediation stories vs blanket re-run.
4. **Profile-drift re-gate procedure** — re-evaluate when `profile.hash` or any pinned toolchain version changes; explicit gate-file invalidation rules.
5. **Operator takeover checklist** — pause orchestrator, manual `sprint-status` edit, state-document patch, `--resume`; safe writes that don't violate BMAD edit-authorization.

Linked from `docs/SECURITY.md`. Mentioned at every FAIL/PARK telemetry event for fast operator handoff.

## 12. TEA compatibility

- Composes TEA outputs (`gate-decision.json`, `e2e-trace-summary.json`) as evidence rather than re-implementing them.
- Adopts TEA's risk model (P×I 1–9 → P0–P3 → coverage thresholds: **P0 = 100% required; P1 = 90% target / 80% minimum; overall ≥ 80% for PASS; P1 80–89% → CONCERNS; < 80% → FAIL**), gate states (PASS/CONCERNS/FAIL/WAIVED), test-quality scoring, burn-in, NFR-evidence categories, and the mandatory "consult fragments + verify against authoritative docs" + Confidence-gate preambles for Generators.
- **Threshold caveat**: exact numeric defaults (coverage %, test-review weights, burn-in N) are **profile-config to re-verify against the live TEA knowledge fragments during M19 planning**.

## 13. Hard Rule 6 → gate mapping (compatibility proof)

Every criterion is covered, none orphaned: (a) reliability·system · (b) resilience·system · (c) durable_hitl·system · (d) blast_radius·system · (e) compliance·code + cert-cadence·release/human · (f) cost_to_serve·system · (g) observability·code.

## 14. Repo-guardrail compatibility (`CLAUDE.md`)

- **No new Python deps**: collectors subprocess the *product's* toolchain; the factory stays stdlib + `filelock` + `psutil`. `doctor` preflights the profile toolchain.
- New `GateDecision` (telemetry) + `GateRendered` (audit) events land in **their own milestone, M01-style**; ride `UnknownEvent` forward-compat until then.
- 500-LOC split: `adjudicator.py` / `gate_rules.py` / `gate_schema.py`; one collector per file.
- One PR per milestone, `bma-d/<slug>` branches, Conventional Commits + `Generated-By` trailer, M-series continues at **M15+**. Artifacts under `_bmad/gate/{risk,evidence,verdicts}/`.

## 15. Innovation / best-in-market properties

1. **Ungameable evidence** — LLM proposes, code disposes, evidence collected in a trust boundary the generator cannot write.
2. **Recursive agentic quality** — an agentic factory that verifies the *product's own* agents (evals/guardrails/constitution-soundness/envelope).
3. **Hard-Rule-6-as-executable-gate** — prose production criteria become a deterministic, replayable, auditable verdict with a logged WAIVED trail.
4. **Profile-as-product-contract** — the production bar is versioned config: uniform, evolvable, reusable across products.
5. **Learning loop** — gate telemetry → retrospective + calibration/drift (M08/M09) auto-tunes the bar (e.g. flake → raise burn-in N).
6. **Mutation-tested AI tests** — defeats the deepest failure mode (tests that pass but assert nothing).

## 16. Milestones (full program; keystone first)

| # | Milestone | Delivers | Dep |
|---|---|---|---|
| M15 | Product Profile | schema + layered loader; policy shape-validator learns `profile`/`gate` keys | — |
| M16 | Factory Self-Trust | evidence-integrity trust boundary + sandbox child + audit P0s | — |
| M17 | Evidence Collectors | polyglot, kill-switched, normalized-evidence emitters — **incl. invariant-DG semgrep runner, pack-schema-v1.2 validator, AIBOM differ, OPA-constitution `opa compile`/`opa test`** | M15 |
| M18 | Adjudicator | pure verdict engine + schemas + gate file + new `GateDecision`/`GateRendered` events (this milestone owns the `telemetry_events.py` delta); `agentic` rule requires pack-schema ok + AIBOM entries present + OPA constitution compiles+tests + evals ≥ threshold; any FAIL-severity invariant violation = hard FAIL (no CONCERNS) | M15,M17 |
| **★ M19** | **Orchestrator Wiring** | step map + verdict control-flow + park-and-continue + BMAD write-back → working code-altitude gate end-to-end; registers `production_ready_gate` in `VALID_VERIFIERS` + `VERIFIERS` (mirrors `review_completion`, fail-closed when gate file absent); ships `docs/operations/gate-troubleshooting.md` (§11.1) | M16,M18 |
| M20 | Risk-scored Readiness | Implementation-Readiness + `validate-create-story` + TEA risk/test-design + `forbidden_until` | M19 |
| M21 | Test-first + Burn-in + Mutation + DoD | atdd-red verify + burn-in + mutation + DoD verifier | M19 |
| M22 | System-altitude Gate | ephemeral-env harness + 5 system collectors + progressive-delivery; `cost_to_serve` collector reads `cost_tier.max_pod_cost_per_tenant` (CONCERNS while DG-2 in `forbidden_until`) | M19 |
| M23 | Learning Loop | gate telemetry → retrospective + calibration/drift → auto-tune profile | M19 |
| M24 (TBD, post-keystone) | **Golden Seed-Template Bundle** | factory-owned (not TEA-provided) bundle (`msme-erp-golden-template@1.x`) pre-wiring Pact contract tests, network-first interception, selector-resilience, data-factories (auto-cleanup), HAR recorder, OTel/SLO/`/healthz`+`/readyz` endpoints — *instantiating* TEA reference fragments (`pact-consumer-framework-setup.md`, `network-first.md`, `selector-resilience.md`, `data-factories.md`, `network-recorder.md`) | M15 |

**M15→M19 is the keystone**: a trustworthy, BMAD-native, deterministic code-altitude production-readiness gate. M24 (seed-template bundle) is the post-keystone follow-up that converts "production-ready from day one" from a property the factory *verifies* into one it *seeds*.

## 17. Risks & open questions

- **Cost/latency of the full collector matrix per story** → mitigated by diff-scoping + budget ceilings + epic-gate full matrix; monitor and tune.
- **Ephemeral full-stack env (M22) is heavy** → tiered envs; most epics use minimal env.
- **TEA numeric thresholds** → re-verify against live fragments during M19 planning.
- **cost-to-serve < ARPU** depends on DG-2 SKU (placeholder) → MSME profile ships zeros + DG-2 in `forbidden_until` so `cost_to_serve` renders CONCERNS, not FAIL, until DG-2 lands.
- **Profile drift** → gate files stamp `profile.hash` + scanner-data snapshot; re-gate triggers on hash change or pinned-toolchain version change (rules in §11.1 runbook §(d)).
- **Seed-template bundle (M24, post-keystone)** → factory-owned `msme-erp-golden-template@1.x`; TBD timing — must land before the factory can claim "production-ready from the first commit" for net-new products (today the gate only *verifies* what generators produce).

## 18. Validation provenance

Reviewed adversarially across BMAD-compat, TEA-compat, factory-integration-feasibility (against `skills/bmad-story-automator/src/story_automator/`), and best-in-market completeness. Fixes folded in: evidence-integrity trust boundary, fail-closed, requirements-traceability vs line-coverage split, test_quality + burn-in + mutation, compliance/performance/accessibility/supply_chain/api_compat/migrations/docs categories, boundary-aware license, richer agentic category, invariant registry, diff-scoping + budget-awareness, BMAD-native remediation + write-back, BMAD hooks (project-context/customize/readiness/correct-course), TEA product-quality patterns, and the repo-guardrail compatibility notes.

**Second adversarial pass (2026-06-20, 6 lenses × 79 agents, pipeline-and-verify):** added (1) concrete invariant-registry entries for DG-12/13/14/25/34 + residency, with DG-14 semgrep semantics; (2) operational criteria for the `agentic` category (pack-schema v1.2, AIBOM diff, OPA constitution compile+test) wired into M17 collectors + M18 rule function (FAIL-severity invariants = hard FAIL, no CONCERNS); (3) `cost_tier` block on Profile + DG-2 in `forbidden_until` so cost_to_serve degrades to CONCERNS until DG-2 SKU lands; (4) corrected TEA coverage thresholds (P0 100% / P1 90% target / 80% min / overall ≥ 80% PASS); (5) gate-checked operator runbook (§11.1) covering verdict interpretation, exhaustion, partial-FAIL, profile drift, takeover; (6) BMAD legacy `drafted`-state mapping note; (7) `production_ready_gate` verifier explicitly slotted for M19 (mirrors `review_completion`, fail-closed on missing gate file); (8) clarified seed_template is factory-owned (not TEA-provided) and added M24 post-keystone milestone to actually build it.
