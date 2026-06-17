# Lifecycle Orchestrator — Core Build Spec (sw-runnable)

> **Scope:** the SAFE, high-value CORE of the full-lifecycle program — the macro layer + the Phase-3→4
> bridge + the Quality & Integrity engine that makes output best-in-class **from day one**. Deliberately
> EXCLUDES the later/under-designed waves (Phase-1/2 PRD & brief, TEA track, WDS design track) — those
> get their own specs after this core is proven. Full design rationale: `lifecycle-orchestrator-spec.md`
> (Parts I–IV). This file is the build input for `sw decompose` / `sw run`.

## Project context & guardrails (apply to EVERY milestone)
- **Extend, don't fork.** This adds a macro lifecycle layer on top of the existing, hardened
  `bmad-story-automator` sprint engine (Python under `skills/bmad-story-automator/src/story_automator/`).
  Phase-4 work delegates to the existing sprint orchestrator — reuse `success_verifiers`, tmux runtime,
  atomic IO, marker/heartbeat, `run_id` telemetry, agent-selection, trust-but-verify.
- **No new third-party Python deps** beyond stdlib + `filelock` + `psutil`. External quality tools
  (mutation/SAST/etc.) are invoked as **subprocesses**, pluggable per stack — never imported.
- **Do NOT modify** `core/telemetry_events.py` (M01-owned). New event types go in a **sibling module**
  (e.g. `core/lifecycle_events.py`).
- **Tests:** `unittest` under `tests/`; canonical gate is the full suite on Linux/WSL (currently
  1482 passing) + `ruff check skills tests` clean (pinned `ruff.toml`). Every milestone must keep both green.
- **Conventional Commits** + `Generated-By:` trailer. Branch `bma-d/<milestone-slug>`; integrate to
  `bma-d/integration-all`; push to the fork `origin` (mira5557373/bmad-automator) — **no upstream PRs.**
- **Eat our own dog food:** obey the simplicity gate (§7) — no gold-plating the orchestrator itself.

## Non-functional requirements
- **No new third-party Python deps** (stdlib + `filelock` + `psutil` only); external quality tools run as pluggable subprocesses.
- **Cross-platform portability:** quality gates pass on Windows git-bash, WSL Ubuntu, and Linux CI without modification; canonical test gate is the Linux/WSL full suite (currently 1482 passing) + `ruff check skills tests` clean.
- **Performance:** the macro layer adds negligible overhead to a sprint; per-node verification is risk-tiered so trivial work is not slowed.
- **Security:** the audit HMAC key is never exposed to child sessions; no secrets in artifacts or logs.
- **Observability:** every node and gate emits correlated (`run_id`) telemetry via the sibling `core/lifecycle_events.py`.
- **Resilience:** all lifecycle state is atomic-write + resumable; macro failures degrade (retry/quarantine/circuit-break), never corrupt the tree.
- **Determinism (tests):** all new tests are deterministic (injected RNG/seed/clock); no network or real-agent calls in unit tests.

## Out of scope (for this core spec)
- BMM Phase-1 analysis/brief and Phase-2 PRD nodes (interactive coached discovery) — separate spec.
- The TEA quality track and the WDS design track — separate specs (WDS↔BMM handoff is the largest open design).
- Phase-6 release/deploy, the dashboard/web UI, multi-component/infra/data topology, and the compliance track — later, tiered.
- Modifying `core/telemetry_events.py`, the changelog vocabulary, or any existing milestone's artifacts.

---

## 1. Macro lifecycle layer — data model & state machine
**Goal:** a phase-DAG scheduler above the per-story sprint engine.
**Requirements:**
- `lifecycle-policy.json` schema: nodes `{id, track, phase, skill, validator_skill?, deps[], input_artifacts[], output_artifact, verifier, gate(human|auto), modes[], agent_role, interactive?}` + `entry{greenfield[],brownfield[]}`. Loader + schema validator.
- `lifecycle-status.yaml`: per-run node states (pending/running/verified/awaiting-approval/approved/complete/failed) + artifact registry; atomic writes (reuse `atomic_write`); resumable.
- Scheduler: a node is runnable when all `deps` are complete+approved and `input_artifacts` exist; topological; bounded concurrency.
**Acceptance:** schema validates + round-trips; scheduler selects correct runnable nodes on fixtures; resume reconstructs state from disk; full suite + ruff green.

## 2. Phase-runner & phase verifiers
**Goal:** execute one node end-to-end, generalizing the sprint engine's spawn→monitor→verify.
**Requirements:**
- `phase-runner`: spawn a child agent for `node.skill` (reuse tmux runtime), monitor to completion, run `node.verifier`; on `track=bmm,phase=4` DELEGATE to the existing sprint orchestrator.
- Phase-verifier registry generalizing `success_verifiers`: `artifact_exists`, `structural_complete` (rejects unresolved placeholder markers in an artifact), and validator-skill wrappers.
- New telemetry in `core/lifecycle_events.py` (sibling, NOT telemetry_events.py): `LifecyclePhaseStarted/Completed/Failed`; correlate with the existing `run_id`.
**Acceptance:** runner drives a node (mocked agent) → verify → advance; phase-4 node calls the sprint engine; events emit with run_id; tests mirror `test_orchestration_loop.py`.

## 3. Approval-gate primitive + decision-support
**Goal:** deliberate human checkpoints that don't degrade to rubber-stamping.
**Requirements:**
- `lifecycle-helper await-approval --node X --artifact P` → record pending gate, emit `LifecycleGatePending`, return PAUSED (clean stop). `approve --node X` / `reject --node X --notes "..."`.
- **reject → course-correct:** re-run node X with `notes` injected as agent context.
- **Approval Packet** at each gate: diff, **assumption ledger**, risks, quality-metric deltas, the specific open questions needing judgment, recommended decision + confidence.
**Acceptance:** gate pauses the loop; approve advances; reject re-runs with notes; packet renders the required fields; tests cover all three paths.

## 4. Entry-mode router & Phase 3→4 bridge (first slice)
**Goal:** greenfield/brownfield entry + the proven first slice.
**Requirements:**
- Entry router: greenfield → start node(s); brownfield → run `bmad-document-project` first.
- **Bridge:** node `B3-epics` runs `bmad-create-epics-and-stories` (input: PRD+architecture) → `epics/`; verifier = `epics_created` (parses with existing `parse-epic`) AND `bmad-check-implementation-readiness` passes; gate = human; on approve, hand `epics/` to the existing sprint orchestrator (`parse-epic → parse-story-range → build-state-doc → per-story loop`).
**Acceptance:** given a PRD+arch fixture, the bridge yields a valid `epics/` the existing `parse-epic` consumes, readiness passes, gate pauses, approval produces a sprint-ready epic; CI-able with a mocked agent.

## 5. Product Quality Charter + charter-driven Definition-of-Done
**Goal:** an explicit, enforced, machine-checkable definition of "best-in-class," from day one.
**Requirements:**
- `quality-charter.yaml`: dimensions (functional, **test-strength**, code-quality, **security**, performance, reliability, observability, accessibility, documentation, supply-chain, maintainability) each with a bar + a verifier reference + a lifecycle cadence; **risk-tiered + configurable**; defaults set a high bar.
- The story verifier set is **charter-driven** (not fixed): Definition-of-Done = in-scope charter dimensions all pass. Charter is also injected into story generation (stories carry their quality requirements).
**Acceptance:** charter loads/validates; a story is marked done ONLY when its in-scope dimensions pass; fixtures prove pass/fail per dimension; configurable tiers work.

## 6. Test-strength engine (anti-gaming) + self-healing loop
**Goal:** "green tests" must be MEANINGFUL, and failures self-heal without lowering the bar.
**Requirements:**
- Test-strength gate: drive **mutation testing** (pluggable per stack, e.g. mutmut for Python) + **property-based** + **metamorphic** test checks; mutation score is a gate.
- **Self-healing loop:** on a failed charter gate, spawn a fix agent (failure as context, triage picks strategy), re-verify, bounded retries, then escalate.
- **Anti-gaming (CRITICAL):** the self-heal loop may **never lower the bar** — reject any fix diff that reduces coverage, deletes/weakens assertions, narrows scope, or relaxes a charter threshold; held-out/rotating verification so agents can't train-to-the-test.
**Acceptance:** a weak/tautological test fails the mutation gate; self-heal raises quality on a seeded failure; a bar-lowering fix diff is rejected; bounded retries + escalation proven; tests cover the anti-gaming rejection explicitly.

## 7. Simplicity / anti-over-engineering gate
**Goal:** "feature-rich" must not become bloat (and the orchestrator must not gold-plate itself).
**Requirements:** a simplicity verifier — "simplest design that meets the charter?"; complexity + dependency budgets (activate the charter maintainability dimension); flag speculative generality/unneeded abstraction/dep sprawl; runnable as a pipeline stage.
**Acceptance:** an over-engineered fixture (needless abstraction/dep) is flagged; a minimal one passes; budgets configurable.

## 8. Product Verification Profile resolver + day-one verification taxonomy
**Goal:** production-readiness from day one — the full APPLICABLE test/bug/vuln set is enforced, stack-conditioned.
**Requirements:**
- Profile resolver (runs at the architecture/charter step): classifies the product (web/API/CLI/library/mobile/data/embeds-AI/infra) and **activates the applicable rows** of the verification taxonomy (test types §35, bug-class hunt list §36, vulnerability classes §37 of the design spec) in the charter.
- Wire the activated gates into per-story (risk-tiered slice) and the release gate (entire applicable set green or FAIL).
- Bug-class hunt list injected into review/test-design prompts so detection is targeted.
**Acceptance:** a CLI profile activates a small subset; a web-service profile activates the full battery (incl. SAST/DAST-stub/SCA/secret/a11y/perf); the release verifier FAILs on any profile-mandatory gap; profile classification tested on fixtures.

## 9. Day-one security gates (per-story)
**Goal:** secure code from the first story.
**Requirements:** per-story pipeline (pluggable subprocesses): **secret-scan**, **SAST**, **dependency/SCA audit**; findings above the charter threshold block the story; results recorded in the provenance/telemetry trail.
**Acceptance:** seeded secret/vulnerable-dep/SAST finding blocks the story; clean code passes; tool invocation is pluggable/config-driven; absence of a tool degrades to a clear "tool-missing" status, not a false pass.

## 10. Learning loop — calibration-driven selection + explore/exploit
**Goal:** the dormant telemetry finally steers selection and improves over time.
**Requirements:**
- `agents-resolve` consults the M08 per-(model, task-kind) success-rate calibration table and prefers the historically-stronger agent/model, with safe fallback.
- **Explore/exploit** (bandit-style): mostly exploit, but explore alternatives to discover better ones; **cold-start** bootstrapping when no data; non-determinism/flake handling via quorum on critical gates.
**Acceptance:** with seeded calibration data, selection prefers the better agent; with no data, falls back safely + explores; exploration rate configurable; deterministic in tests via injected RNG/seed.
