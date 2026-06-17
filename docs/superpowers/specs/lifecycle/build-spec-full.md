# Lifecycle Orchestrator — FULL Build Spec (sw-runnable, dependency-waved)

> Widened from the core to the **full capability set** of `design-spec.md` (Parts I–IV — read it for
> the detailed rationale/requirements behind each section below; this file is the buildable contract).
> Ordered into **dependency waves**: highest-value / lowest-risk first, WDS (riskiest) last. `sw` runs
> waves in dependency order; independent milestones within a wave may run in parallel and merge into
> this one branch (`bma-d/lifecycle-full`).

## Project context & guardrails (apply to EVERY milestone)
- **Extend the existing hardened `bmad-story-automator` engine** (Python under
  `skills/bmad-story-automator/src/story_automator/`). Phase-4 delegates to the existing sprint
  orchestrator; reuse `success_verifiers`, tmux runtime, atomic IO, marker/heartbeat, `run_id`
  telemetry, agent-selection, trust-but-verify. Some Wave-0 work (the macro data model / scheduler) is
  already partially committed — build on it, don't duplicate.
- **No new third-party Python deps** beyond stdlib + `filelock` + `psutil`. External quality/security
  tools (mutation, SAST, DAST, fuzz, SBOM, IaC scan…) run as **pluggable subprocesses**, never imported;
  absence of a tool degrades to a clear "tool-missing" status, never a false pass.
- **Do NOT modify** `core/telemetry_events.py` (M01-owned). New event types go in sibling modules
  (`core/lifecycle_events.py`).
- **Tests:** `unittest` under `tests/`; deterministic (injected RNG/seed/clock; no network/real-agent in
  unit tests). Canonical gate = the full suite on Linux/WSL + `ruff check skills tests` clean. Every
  milestone keeps both green.
- **Conventional Commits** + `Generated-By:` trailer. All work merges into `bma-d/lifecycle-full`.
- **Obey the simplicity gate (Wave 1 §7):** no gold-plating; simplest design meeting the charter.

## Non-functional requirements
Portability (Windows git-bash / WSL / Linux CI) of all gates; negligible macro-layer overhead;
secrets never exposed to child sessions or artifacts; correlated `run_id` telemetry on every node/gate;
atomic + resumable lifecycle state; all new tests deterministic.

## Out of scope
Modifying `telemetry_events.py`, the changelog vocabulary, or historical milestone artifacts.

---

# WAVE 0 — Foundation (macro layer)  [design-spec §3]

## 1. Lifecycle data model & DAG scheduler
`lifecycle-policy.json` node schema (id, track, phase, skill, validator_skill?, deps[], input_artifacts[],
output_artifact, verifier, gate(human|auto), modes[], agent_role, interactive?) + entry{greenfield,
brownfield}; loader+validator; `lifecycle-status.yaml` per-run node states + artifact registry
(atomic_write reuse); topological scheduler with bounded concurrency; resumable from disk.
**Accept:** schema round-trips; scheduler selects correct runnable nodes; resume reconstructs state.

## 2. Phase-runner & phase verifiers
Spawn child agent for `node.skill` (tmux reuse), monitor, run verifier; **delegate to existing sprint
orchestrator on track=bmm,phase=4**. Verifier registry generalizing `success_verifiers`
(`artifact_exists`, `structural_complete`, validator-skill wrappers). New `core/lifecycle_events.py`
(`LifecyclePhaseStarted/Completed/Failed`, run_id-correlated). **Accept:** runs a node end-to-end
(mocked agent) → verify → advance; phase-4 delegates; events emit; mirrors `test_orchestration_loop.py`.

## 3. Approval-gate primitive + decision-support  [design-spec §25]
`lifecycle-helper await-approval/approve/reject(+notes)`; reject re-runs node with notes as context;
**Approval Packet** (diff, assumption ledger, risks, quality-metric deltas, open questions, recommended
decision+confidence). **Accept:** pause/approve/reject paths + packet fields tested.

## 4. Entry-mode router & Phase 3→4 bridge  [design-spec §6]
Greenfield→start node; brownfield→`bmad-document-project` first. `B3-epics` runs
`bmad-create-epics-and-stories` (PRD+arch input) → `epics/`; verifier = `epics_created` (existing
`parse-epic`) AND `bmad-check-implementation-readiness`; human gate; on approve hand `epics/` to the
sprint orchestrator. **Accept:** CI-able fixture, mocked agent, end-to-end to a sprint-ready epic.

---

# WAVE 1 — Quality & Integrity core  [design-spec §11–§12, §23, §28, §15]

## 5. Product Quality Charter + charter-driven DoD  [§11]
`quality-charter.yaml`: dimensions (functional, test-strength, code-quality, security, performance,
reliability, observability, accessibility, documentation, supply-chain, maintainability), each bar +
verifier ref + cadence; risk-tiered, configurable, high-bar defaults; injected into story generation.
DoD = in-scope dimensions all pass. **Accept:** loads/validates; story done iff in-scope dims pass;
per-dimension pass/fail fixtures.

## 6. Test-strength + self-heal + anti-gaming integrity  [§12.2–.3, §23]
Pluggable mutation testing + property-based + metamorphic checks; mutation score gate. Self-heal loop
(fix agent w/ failure context, triage strategy, bounded retries, escalation). **Anti-gaming: the
self-heal loop may NEVER lower the bar** — reject any diff that reduces coverage / deletes-weakens
assertions / narrows scope / relaxes a threshold; held-out/rotating verification. **Accept:** weak test
fails mutation gate; self-heal raises quality on seeded failure; bar-lowering diff rejected (explicit test).

## 7. Simplicity / anti-over-engineering gate  [§28]
"Simplest design meeting the charter?" verifier; complexity + dependency budgets; flag speculative
generality / unneeded abstraction / dep sprawl. **Accept:** over-engineered fixture flagged; minimal passes.

## 8. Verification-Profile resolver + day-one taxonomy framework  [§35–§38]
Resolver classifies product (web/API/CLI/library/mobile/data/embeds-AI/infra) and activates applicable
rows of the verification taxonomy in the charter; wires gates into per-story (risk-tiered) + release
(entire applicable set green or FAIL); bug-class hunt list injected into review/test-design prompts.
**Accept:** CLI profile→subset; web-service→full battery; release verifier FAILs on a profile-mandatory gap.

## 9. Per-story security gates  [§13 partial]
Pluggable subprocesses: secret-scan, SAST, dependency/SCA; findings above charter threshold block the
story; recorded in telemetry. **Accept:** seeded secret/vuln-dep/SAST finding blocks; clean passes;
tool-missing degrades clearly.

## 10. Learning loop — calibration selection + explore/exploit  [§15, §27]
`agents-resolve` consults M08 per-(model,task) calibration; prefers stronger agent w/ safe fallback;
bandit-style explore/exploit; cold-start bootstrap; quorum on non-deterministic gates. **Accept:**
seeded data drives selection; no-data fallback+explore; deterministic via injected RNG.

---

# WAVE 2 — Excellence extras  [design-spec §12.4–.8]

## 11. Multi-candidate tournaments + judge panels  [§12.4]
For the architecture node + high-risk stories: generate K diverse candidates, score each with a parallel
judge panel vs charter+rubric, synthesize from the winner. **Accept:** K-candidate flow produces a
scored winner on a fixture; judges diverse; deterministic via seed.

## 12. Red-team adversarial stage  [§12.8]
Per-epic adversarial agents attack output (security exploits, edge cases, chaos/error injection) before
the release gate; findings feed back as stories/fixes. **Accept:** seeded vulnerable output is flagged
by the red-team stage.

## 13. Performance budgets + observability-as-requirement  [§12.6–.7]
Perf budgets set at architecture, enforced per story via benchmarks (regression blocks); story generation
injects observability ACs; verifier checks logs/metrics/traces/health exist. **Accept:** a perf
regression blocks; missing-observability output fails the gate.

## 14. Risk-adaptive verification routing  [§12.5]
Risk/complexity score drives verification depth (high-risk → tournaments+mutation+red-team; trivial →
fast path). **Accept:** routing selects depth by risk on fixtures.

---

# WAVE 3 — Full security & verification drivers  [design-spec §13, §35–§37]

## 15. Dynamic security: DAST + IAST  [§37]
Pluggable DAST (e.g. ZAP) against a running build; IAST where available. **Accept:** seeded injectable
endpoint flagged; clean passes; tool-missing degrades.
## 16. Fuzzing  [§35]
Coverage-guided + grammar/API fuzz for parsers/APIs/untrusted input. **Accept:** seeded crash found.
## 17. Threat-model + SBOM + license/IP  [§13, §37]
Per-epic STRIDE threat model feeding stories; SBOM generation; license compliance incl. LLM-emitted code.
**Accept:** SBOM produced; incompatible license flagged; threat model artifact gates the epic.
## 18. IaC + container/image + cloud-misconfig scanning  [§37]
Pluggable tfsec/checkov/trivy. **Accept:** seeded misconfig/vuln image flagged (profile-gated).
## 19. API + LLM security (conditional)  [§37]
OWASP API Top 10 (BOLA…) checks; OWASP LLM Top 10 (prompt-injection, insecure output) when product
embeds AI. **Accept:** seeded BOLA / prompt-injection flagged; off when profile excludes.
## 20. Crypto correctness + privacy/PII  [§37, §31]
Weak-crypto/randomness/key-mgmt checks; PII/data-protection (GDPR/HIPAA) checklist (tiered by domain).
**Accept:** weak-crypto + unencrypted-PII fixtures flagged.
## 21. Full test-type drivers  [§35]
Pluggable drivers: load/stress/soak/volume, chaos/failover/DR, concurrency/race/deadlock, compatibility
(cross-OS/browser/back-compat), i18n/l10n, visual-regression/snapshot, DB integrity/migration. Each
profile-gated. **Accept:** each driver runs on a fixture + reports through the charter; release gate
aggregates.

---

# WAVE 4 — Knowledge & Learning maturity  [design-spec §14, §27]

## 22. Project KB + standards injection
Project KB (coding standards, arch constraints, conventions, glossary) injected (focused/RAG) into every
child agent. **Accept:** KB content reaches a child agent's context on a fixture.
## 23. ADR ledger + standards-conformance verifier
ADRs recorded + enforced; verifier checks output conforms to KB/ADRs. **Accept:** an ADR-violating change
is flagged.
## 24. Cross-run memory (retro→forward)
Phase-5 retro learnings + drift findings fed forward into the next epic/run (reuse WDS memory/sync +
BMAD project-context). **Accept:** a prior-run learning influences the next run's context.
## 25. Judge calibration + model-version canary + flake handling  [§27]
Periodic human-eval calibrates automated judges; model/prompt-change canary compares quality before
adopting; flake/quorum on non-deterministic gates. **Accept:** canary blocks a regressing model;
flake detection + quorum tested.

---

# WAVE 5 — Intent, consistency, innovation, self-eval  [design-spec §24, §26, §29, §30]

## 26. Intent/requirements quality + Definition-of-Ready  [§24]
Intent Charter (PRD/epics/stories unambiguous/complete/testable/consistent); ambiguity/completeness/
conflict/AC-quality gates; Definition-of-Ready before sprint entry. **Accept:** ambiguous/incomplete
requirement flagged; under-ready story blocked from sprint.
## 27. Cross-artifact consistency + change propagation  [§26]
Continuous bidirectional traceability (PRD↔arch↔epic↔story↔code↔test); change-impact analysis on
course-correct re-opens affected nodes. **Accept:** code drifting from PRD flagged; a PRD change computes
+ re-opens the downstream set.
## 28. Innovation / feature-ideation engine (gated, opt-in)  [§29]
Agent proposes enhancements beyond literal requirements (delight, competitive parity, edge-case UX),
human-gated into the backlog; opt-in per project; subject to the simplicity gate. **Accept:** ideation
produces gated suggestions; opt-out disables it.
## 29. Automation self-eval: benchmark + human-eval rubric  [§30]
Reference-project benchmark corpus scored per charter across automation releases (extends golden-trace);
output-excellence human-eval rubric calibrates judges. **Accept:** benchmark run produces per-charter
scores + a trend record.

---

# WAVE 6 — BMM lifecycle phases (greenfield + brownfield)  [design-spec Part I]

## 30. BMM Phase-1 analysis/brief node (gated)
`bmad-product-brief` (+research) in draft-with-assumptions mode → `product-brief.md`; structural verifier;
human gate (assumption ledger). **Accept:** node produces a brief; gate pauses with assumptions surfaced.
## 31. BMM Phase-2 PRD node (gated)
`bmad-create-prd` (draft-with-assumptions) → `bmad-validate-prd`; human gate. **Accept:** PRD produced,
`validate-prd` passes, gate pauses.
## 32. BMM Phase-5 retrospective node
`bmad-retrospective` at lifecycle end; feeds cross-run memory (§24). **Accept:** retro artifact produced
+ learnings captured.

---

# WAVE 7 — TEA quality track  [design-spec § TEA]

## 33. TEA test-design (system + per-epic)
`bmad-testarch-test-design` at architecture + per epic → risk matrix + P0–P3 test plan feeding story
generation. **Accept:** test plan artifact produced + consumed by story creation.
## 34. TEA nfr-assess + trace release gate
`bmad-testarch-nfr` + `bmad-testarch-trace`; P0–P3 risk gate (PASS/CONCERNS/FAIL); **P0 FAIL blocks the
release node**. **Accept:** coverage-gap fixture → FAIL blocks release; full coverage → PASS.

---

# WAVE 8 — Operability & release  [design-spec §16–§20]

## 35. Provenance ledger + run report  [§17]
Every artifact records agent/model/prompt/inputs (extends audit log); end-of-run report (per-charter
metrics, cost, gates, learnings). **Accept:** provenance recorded per artifact; report renders.
## 36. Execution isolation  [§18]
Per-story git worktree isolation (reuse worktree support) so a bad agent can't corrupt the tree + parallel
stories don't collide; merge on green; per-node resource/time bounds. **Accept:** two stories run isolated
+ merge cleanly; a failing story doesn't corrupt the main tree.
## 37. Operator dashboard + gate notifications  [§19]
`lifecycle-helper status --dashboard` (DAG, node states, pending gates, charter metrics, cost); pending
gate notifications via configurable webhook. **Accept:** dashboard renders state; a pending gate fires a
notification hook.
## 38. Macro failure governance  [§20]
Per-node max-retries + escalation; artifact quarantine + rollback; circuit breakers; partial-failure
handling. **Accept:** a repeatedly-failing node quarantines + escalates; one story's failure doesn't halt others.
## 39. Phase-6 release/deploy node  [§16]
Scaffold the PRODUCT's CI/CD, semantic versioning, changelog generation, release artifacts, deploy,
smoke/canary, rollback plan; gated by TEA trace + charter. **Accept:** release node produces a versioned,
changelogged, gated release artifact on a fixture.

---

# WAVE 9 — WDS design track (highest-risk; LAST)  [design-spec § WDS, §32]

## 40. WDS install + config + memory/sync integration
Install the WDS expansion module + its config; integrate its memory/sync tools. **Accept:** WDS skills
resolve + config loads in a fixture project.
## 41. WDS design-track orchestration
Drive Saga (ph1-2 brief/trigger-map) + Freya (ph3-4 scenarios/ux-design) as lifecycle nodes producing
design artifacts. **Accept:** the design-track nodes run + produce scenario/ux-design artifacts (mocked agent).
## 42. WDS→BMM artifact handoff (HIGHEST UNKNOWN)
Make WDS scenarios/ux-design/design-system machine-consumable as inputs to BMM `create-prd`/
`create-architecture`/`create-story`. **Accept:** a WDS ux-design artifact is consumed as input context by
a BMM node on a fixture; mapping documented.
## 43. WDS ph5-8
agentic-development overlap with BMM Phase-4, asset-generation, design-system, product-evolution as
lifecycle nodes. **Accept:** each phase node runs + produces its artifact (mocked agent).

---

# WAVE 10 — Topology & scale (TIERED — enable per project shape)  [design-spec §32]

## 44. Multi-component + contracts + IaC + data
Multi-component/monorepo DAG (a node-graph per component) + cross-component contract testing (Pact) +
infrastructure-as-code phase + data track (schema/migrations/quality). Profile-gated; off for
single-codebase. **Accept:** a 2-component fixture orchestrates both + a contract test gates their interface.


---

## Implementation status

- **W0-M01 (Lifecycle data model + DAG scheduler)** — landed 2026-06-17. Three modules: `core/lifecycle_policy.py`, `core/lifecycle_status.py`, `core/lifecycle_scheduler.py`. Scheduler is a pure function (no IO, no execution); status persistence uses `core.atomic_io.write_atomic_text`. Status file is JSON (`lifecycle-status.json`) — see plan §2 for the no-deps rationale around the spec's `.yaml` filename. Phase-runner, verifiers, gates, telemetry events, and CLI surface remain unimplemented and are scheduled for W0-M02 / W0-M03 / W0-M04 respectively.

- **W0-M02 (Phase runner + phase verifiers)** — landed 2026-06-17. Three new modules: `core/lifecycle_events.py` (LifecyclePhaseStarted/Completed/Failed typed events auto-registered into `Event._REGISTRY`), `core/lifecycle_verifiers.py` (sibling registry of `artifact_exists`, `structural_complete`, `validator_skill`), `core/lifecycle_runner.py` (single-turn `run_next_node` with injected spawn/monitor/delegate/verifier boundaries; atomic per-transition status persistence; run_id-correlated telemetry). The approval-gate primitive, entry-mode router CLI, and W0-M04 lifecycle-helper command surface remain scheduled for the next milestones. `core/telemetry_events.py` and `core/success_verifiers.py` were not modified.
