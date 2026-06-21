# Multi-Module Compatibility Roadmap (M25–M60)

This roadmap sequences 36 follow-on milestones that close the remaining
compatibility deltas between the production-ready factory gate (see
`2026-06-20-production-ready-factory-design.md`) and the broader BMAD
ecosystem (`bma-d/bmad-story-automator-go` reference repo, BMAD-METHOD
core process, sprint/risk artefacts, BMAD-review adversarial pipeline,
and the upstream BMAD-AUTO orchestration substrate).

Each row names a single milestone. Owners are Python module paths
under `skills/bmad-story-automator/src/story_automator/` (relative
roots `core/`, `commands/`, `adapters/`, `data/`). Plan files are
expected to land under `docs/superpowers/plans/` with the dated prefix
`2026-06-21-` and the milestone slug suffix. All work obeys the hard
guardrails in `CLAUDE.md`: stdlib + `filelock` + `psutil` only, never
modify `core/telemetry_events.py`, 500-LOC soft limit, conventional
commits with `Generated-By: claude-opus-4-7` trailer, no
whitespace-only churn.

The roadmap is partitioned into three waves. Wave 1 (M25–M43) is
**foundational**: schemas, dispatch tables, profile composition, and
the bridges into the existing gate subsystem. Wave 2 (M44–M52) is
**integrative**: cross-skill bridges, sprint/phase mapping, ADR-29
acceptance, and replay primitives. Wave 3 (M53–M60) is **research
delta**: ramr cache, Merkle NFR ledger, anti-bias roundtrip,
adversarial-by-construction, kernel violation classifier.

| M   | Wave | Title                                  | Owner module(s)                                                                                  | Depends on    | Plan file (relative path)                                                       | Status  | Effort (LOC/wk) |
| --- | ---- | -------------------------------------- | ------------------------------------------------------------------------------------------------ | ------------- | ------------------------------------------------------------------------------- | ------- | --------------- |
| M25 | 1    | Phase bridge                           | `core/phase_bridge.py`, `core/gate_orchestrator.py`                                              | gate-m10      | `docs/superpowers/plans/2026-06-21-m25-phase-bridge.md`                         | planned | 220 / 0.5w      |
| M26 | 1    | Gate-rules priority resolver           | `core/gate_rules.py`, `core/adjudicator.py`                                                      | gate-m9 stub  | `docs/superpowers/plans/2026-06-21-m26-gate-rules-priority.md`                  | planned | 300 / 1w        |
| M27 | 1    | Story keys + epic retro                | `core/story_keys.py`, `core/epic_retro.py`                                                       | M25           | `docs/superpowers/plans/2026-06-21-m27-story-keys-epic-retro.md`                | planned | 280 / 1w        |
| M28 | 1    | Story writer                           | `core/story_writer.py`, `commands/story_writer_cmd.py`                                           | M27           | `docs/superpowers/plans/2026-06-21-m28-story-writer.md`                         | planned | 320 / 1w        |
| M29 | 1    | Story status state machine             | `core/story_status.py`                                                                           | M28           | `docs/superpowers/plans/2026-06-21-m29-story-status.md`                         | planned | 260 / 0.5w      |
| M30 | 1    | TEA emit pipeline                      | `core/tea_emit.py`, `core/risk_profile.py`                                                       | gate-m12      | `docs/superpowers/plans/2026-06-21-m30-tea-emit.md`                             | planned | 240 / 0.5w      |
| M31 | 1    | Deferred-work ledger                   | `core/deferred_work.py`                                                                          | gate-m10      | `docs/superpowers/plans/2026-06-21-m31-deferred-work.md`                        | planned | 260 / 0.5w      |
| M32 | 1    | CLI profile selector                   | `commands/profile_cmd.py`, `core/product_profile.py`                                             | gate-m1       | `docs/superpowers/plans/2026-06-21-m32-cli-profile.md`                          | planned | 200 / 0.5w      |
| M33 | 1    | Review taxonomy                        | `core/review_taxonomy.py`                                                                        | none          | `docs/superpowers/plans/2026-06-21-m33-review-taxonomy.md`                      | planned | 220 / 0.5w      |
| M34 | 1    | Coverage status normalizer             | `core/coverage_status.py`, `core/collectors/correctness.py`                                      | gate-m5       | `docs/superpowers/plans/2026-06-21-m34-coverage-status.md`                      | planned | 240 / 0.5w      |
| M35 | 1    | Test levels (unit/integration/e2e)     | `core/test_levels.py`                                                                            | M34           | `docs/superpowers/plans/2026-06-21-m35-test-levels.md`                          | planned | 260 / 1w        |
| M36 | 1    | Kernel schema                          | `core/kernel_schema.py`                                                                          | none          | `docs/superpowers/plans/2026-06-21-m36-kernel-schema.md`                        | planned | 320 / 1w        |
| M37 | 1    | Risk action bands                      | `core/risk_action_bands.py`, `core/risk_profile.py`                                              | gate-m12      | `docs/superpowers/plans/2026-06-21-m37-risk-action-bands.md`                    | planned | 220 / 0.5w      |
| M38 | 1    | Sprint schema                          | `core/sprint_schema.py`                                                                          | M36           | `docs/superpowers/plans/2026-06-21-m38-sprint-schema.md`                        | planned | 280 / 1w        |
| M39 | 1    | Policy translator                      | `core/policy_translator.py`, `core/runtime_policy.py`                                            | M33, M36      | `docs/superpowers/plans/2026-06-21-m39-policy-translator.md`                    | planned | 300 / 1w        |
| M40 | 1    | Result JSON (bmad-auto contract)       | `core/result_json_bauto.py`                                                                      | M36           | `docs/superpowers/plans/2026-06-21-m40-result-json-bauto.md`                    | planned | 240 / 0.5w      |
| M41 | 1    | Escalation emit                        | `core/escalation_emit.py`                                                                        | M40           | `docs/superpowers/plans/2026-06-21-m41-escalation-emit.md`                      | planned | 220 / 0.5w      |
| M42 | 1    | Hook env (`BMAD_AUTO_*`)               | `core/hook_env.py`, `commands/orchestrator.py`                                                   | M40, M41      | `docs/superpowers/plans/2026-06-21-m42-hook-env-bmad-auto.md`                   | planned | 200 / 0.5w      |
| M43 | 1    | Install paths seed                     | `core/install_paths.py`, `install.sh`                                                            | M42           | `docs/superpowers/plans/2026-06-21-m43-install-paths-seed.md`                   | planned | 240 / 0.5w      |
| M44 | 2    | Profile composer                       | `core/profile_composer.py`, `core/product_profile.py`                                            | M32, M36, M39 | `docs/superpowers/plans/2026-06-21-m44-profile-composer.md`                     | planned | 360 / 1w        |
| M45 | 2    | bmad-review bridge                     | `core/bmad_review_bridge.py`, `adapters/bmad_review.py`                                          | M33, M39, M40 | `docs/superpowers/plans/2026-06-21-m45-bmad-review-bridge.md`                   | planned | 340 / 1w        |
| M46 | 2    | Risk -> story DAR (decisions/assumes)  | `core/risk_to_story_dar.py`, `core/story_writer.py`                                              | M28, M30, M37 | `docs/superpowers/plans/2026-06-21-m46-risk-to-story-dar.md`                    | planned | 280 / 1w        |
| M47 | 2    | Waiver -> escalation routing           | `core/waiver_to_escalation.py`, `core/gate_schema.py`                                            | M41, M44      | `docs/superpowers/plans/2026-06-21-m47-waiver-to-escalation.md`                 | planned | 240 / 0.5w      |
| M48 | 2    | Sprint <-> phase map                   | `core/sprint_phase_map.py`                                                                       | M25, M38      | `docs/superpowers/plans/2026-06-21-m48-sprint-phase-map.md`                     | planned | 220 / 0.5w      |
| M49 | 2    | Worktree baseline                      | `core/worktree_baseline.py`, `core/trust_boundary.py`                                            | gate-m3       | `docs/superpowers/plans/2026-06-21-m49-worktree-baseline.md`                    | planned | 280 / 1w        |
| M50 | 2    | Usage parsers (Claude/Codex/Gemini)    | `core/usage_parsers.py`, `adapters/tmux.py`                                                      | none          | `docs/superpowers/plans/2026-06-21-m50-usage-parsers.md`                        | planned | 340 / 1w        |
| M51 | 2    | ADR-29 acceptance criterion            | `core/adr29_criterion.py`, `core/adjudicator.py`                                                 | M26, M39      | `docs/superpowers/plans/2026-06-21-m51-adr-29-criterion.md`                     | planned | 240 / 0.5w      |
| M52 | 2    | Scalability collector                  | `core/collectors/scalability.py`, `core/checks/scalability_check.py`                             | gate-m4       | `docs/superpowers/plans/2026-06-21-m52-scalability-collector.md`                | planned | 320 / 1w        |
| M53 | 3    | RAMR (rolling-action memo register)    | `core/ramr.py`                                                                                   | M31, M46      | `docs/superpowers/plans/2026-06-21-m53-ramr.md`                                 | planned | 380 / 1w        |
| M54 | 3    | Merkle NFR ledger                      | `core/merkle_nfr_ledger.py`, `core/evidence_io.py`                                               | gate-m2, M52  | `docs/superpowers/plans/2026-06-21-m54-merkle-nfr-ledger.md`                    | planned | 360 / 1w        |
| M55 | 3    | Anti-bias phase roundtrip              | `core/anti_bias_roundtrip.py`, `core/phase_bridge.py`                                            | M25, M45      | `docs/superpowers/plans/2026-06-21-m55-anti-bias-phase-roundtrip.md`            | planned | 300 / 1w        |
| M56 | 3    | Stack risk weights                     | `core/stack_risk_weights.py`, `core/risk_profile.py`                                             | M37, M44      | `docs/superpowers/plans/2026-06-21-m56-stack-risk-weights.md`                   | planned | 260 / 0.5w      |
| M57 | 3    | Adversarial review by construction     | `core/adversarial_review_byc.py`, `core/bmad_review_bridge.py`                                   | M45, M51      | `docs/superpowers/plans/2026-06-21-m57-adversarial-review-by-construction.md`   | planned | 380 / 1w        |
| M58 | 3    | Cross-CLI replay diff                  | `core/cross_cli_replay.py`, `core/usage_parsers.py`                                              | M50, M54      | `docs/superpowers/plans/2026-06-21-m58-cross-cli-replay-diff.md`                | planned | 340 / 1w        |
| M59 | 3    | Phase-shaped budgets                   | `core/phase_shaped_budgets.py`, `core/runtime_policy.py`                                         | M25, M39      | `docs/superpowers/plans/2026-06-21-m59-phase-shaped-budgets.md`                 | planned | 300 / 1w        |
| M60 | 3    | Kernel violation classifier            | `core/kernel_violation_classifier.py`, `core/kernel_schema.py`, `core/adjudicator.py`            | M36, M51, M55 | `docs/superpowers/plans/2026-06-21-m60-kernel-violation-classifier.md`          | planned | 360 / 1w        |

## Wave 1 milestone summaries (M25–M43)

- **M25 phase-bridge** — Map gate-orchestrator phase IDs (`readiness`,
  `generation`, `gate`, `remediation`) onto the BMAD-METHOD phase
  vocabulary (`discover`, `design`, `build`, `verify`, `ship`). Pure
  translation table plus a round-trip property test.
- **M26 gate-rules-priority** — Fill in the `gate_rules.py` stub from
  the m9 placeholder: priority resolver consumes
  `product_profile.required_for_priority` and emits a deterministic
  rule order for the adjudicator.
- **M27 story-keys-epic-retro** — Canonical `<epic>.<story>` key
  parser plus a one-shot retroactive epic-key audit on existing
  evidence files.
- **M28 story-writer** — Generator for `story.md` skeletons keyed off
  M27 keys; downstream of gate-m12 readiness so blocked stories
  cannot be written.
- **M29 story-status** — Finite-state machine for story status
  transitions (`draft -> ready -> in_progress -> review -> done`).
  Mirrors the bmad-story-automator-go state shape.
- **M30 tea-emit** — TEA (Test Engineering Architect) evidence
  emission helper feeding the risk profile from m12.
- **M31 deferred-work** — Persistent ledger of work intentionally
  deferred by the gate (e.g. `[DEFERRED]` changelog entries, parked
  stories, mitigation debt). Read by Wave-3 RAMR.
- **M32 cli-profile** — `gate profile select <name>` CLI subcommand
  driven by `product_profile.load_effective_profile`.
- **M33 review-taxonomy** — Closed enum of review-finding categories
  shared by bmad-review and the adjudicator.
- **M34 coverage-status** — Normalize coverage outputs from the
  correctness collector into a profile-aware status enum.
- **M35 test-levels** — Tag tests as `unit | integration | e2e`; the
  gate budgets these independently per profile.
- **M36 kernel-schema** — JSON schema for the kernel contract shared
  with bmad-auto. Most-depended-on Wave 1 row.
- **M37 risk-action-bands** — Translate risk scores (m12) into action
  bands (`accept`, `mitigate`, `block`).
- **M38 sprint-schema** — Sprint artefact JSON schema (carries
  capacity, phase map, risk bands).
- **M39 policy-translator** — Convert bmad-auto policy DSL into
  `runtime_policy` entries.
- **M40 result-json-bauto** — Emit gate decisions in the bmad-auto
  Result JSON envelope; critical-path row for the contract.
- **M41 escalation-emit** — Escalation messages produced when a gate
  blocks past its mitigation budget.
- **M42 hook-env-bmad-auto** — `BMAD_AUTO_*` env-var contract so the
  orchestrator child can hand off to bmad-auto.
- **M43 install-paths-seed** — Seed install paths inside `install.sh`
  for bmad-auto co-installation; closes the foundational wave.

## Wave 2 milestone summaries (M44–M52)

- **M44 profile-composer** — Compose multiple profiles (e.g. base +
  msme-erp overlay) with deterministic merge semantics.
- **M45 bmad-review-bridge** — Adapter that drives the bundled
  `bmad-story-automator-review` skill via the new bridge module.
- **M46 risk-to-story-dar** — Lift risk-profile entries into the
  Decisions/Assumptions/Risks block of `story.md`.
- **M47 waiver-to-escalation** — Route gate waivers into the M41
  escalation pipeline when they exceed their lifetime.
- **M48 sprint-phase-map** — Bind sprint artefacts (M38) to phase
  identifiers (M25).
- **M49 worktree-baseline** — Reproducible worktree baselining on top
  of the gate-m3 trust boundary; enables Wave-3 replay.
- **M50 usage-parsers** — Parse Claude / Codex / Gemini CLI usage
  output into a shared token-accounting envelope; reused by M58.
- **M51 adr-29-criterion** — Acceptance criterion for ADR-29 (the
  research-derived "no silent block" rule) wired into the
  adjudicator.
- **M52 scalability-collector** — New collector under
  `core/collectors/scalability.py` honouring the m4 contract.

## Wave 3 milestone summaries (M53–M60)

- **M53 ramr** — Rolling Action Memo Register: dedupe of M31 deferred
  work and M46 risk-derived assumptions into a single per-epic memo.
- **M54 merkle-nfr-ledger** — Hash-chain NFR evidence (m2 + M52) into
  a Merkle ledger so replay diffs can target subtrees.
- **M55 anti-bias-roundtrip** — Phase-bridge (M25) plus bmad-review
  bridge (M45) drive an anti-bias roundtrip: a finding emitted in one
  phase must survive translation to the next phase unchanged.
- **M56 stack-risk-weights** — Per-stack risk weights overlaying the
  generic risk action bands (M37).
- **M57 adversarial-review-byc** — Generate adversarial test cases by
  construction from bmad-review findings and ADR-29 acceptance.
- **M58 cross-cli-replay** — Replay the same gate run across Claude /
  Codex / Gemini CLIs (via M50) and diff the Merkle ledger (M54).
- **M59 phase-shaped-budgets** — Per-phase budget ceilings layered on
  top of `runtime_policy`; closes the Wave-3 contract with the gate
  budget machinery.
- **M60 kernel-violation-classifier** — Classify kernel-schema (M36)
  violations into ADR-29 (M51) and anti-bias (M55) categories;
  capstone milestone of the roadmap.

## Status legend

- `planned` — milestone has a roadmap row; plan file not yet written.
- `drafted` — plan file exists under `docs/superpowers/plans/`; tests
  not yet written.
- `in-progress` — at least one failing test landed on a feature branch
  `bma-d/compat-mNN-<slug>`; implementation underway.
- `tagged` — implementation merged; tag `compat-mNN-<slug>` exists on
  the default branch and points at the merge commit.
- `superseded` — replaced by a later milestone; row is kept for
  audit-trail continuity, body explains the supersession.
- `deferred` — out of scope for this roadmap window; tracked here so
  the dependency graph stays connected.

Tag naming repeats the convention used by the gate roadmap: every
completed milestone gets exactly one annotated tag of the form
`compat-mNN-<slug>` whose message contains the conventional-commit
subject of the merge commit. No floating tags, no force-moves.

## Dependencies graph (ASCII)

```
Wave 1 (foundational)

gate-m1 -----> M32 ----+
                       |
gate-m4 -----> M52 (W2)
gate-m5 -----> M34 ---> M35
gate-m10 ----> M25 ---> M27 ---> M28 ---> M29
            \   |              \
             \  +--> M31        +--> M46 (W2)
              \
               +--> M48 (W2, with M38)

gate-m12 ----> M30 ---> M37 ---> M46 (W2)

(none) ------> M33 ----+
(none) ------> M36 ----+--> M39 ---> M40 ---> M41 ---> M42 ---> M43
                       |             |
                       +--> M38 -----+--> M48 (W2)
                       |
                       +--> M40 (above)
                       +--> M44 (W2)
                       +--> M60 (W3)

Wave 2 (integrative)

M32 + M36 + M39 -----------> M44 ----+
M33 + M39 + M40 -----------> M45 ----+--> M55 (W3)
M28 + M30 + M37 -----------> M46 ----+--> M53 (W3)
M41 + M44 ----------------> M47
M25 + M38 ----------------> M48
gate-m3 ------------------> M49
(none) -------------------> M50 ----+--> M58 (W3)
M26 + M39 ----------------> M51 ----+--> M57 (W3), M60 (W3)
gate-m4 ------------------> M52 ----+--> M54 (W3)

Wave 3 (research delta)

M31 + M46 ----------------> M53
gate-m2 + M52 ------------> M54 ----+--> M58 (W3)
M25 + M45 ----------------> M55 ----+--> M60 (W3)
M37 + M44 ----------------> M56
M45 + M51 ----------------> M57
M50 + M54 ----------------> M58
M25 + M39 ----------------> M59
M36 + M51 + M55 ----------> M60
```

Notes on the graph:

- Every Wave 2 milestone has at least one Wave 1 parent. Wave 3 in
  turn pulls only from Wave 1 and Wave 2 (never sideways inside Wave
  3), which keeps the topological order stable if a milestone slips.
- `gate-mNN` parents reference the existing factory-gate milestones
  documented in `docs/superpowers/specs/2026-06-20-production-ready-factory-design.md`
  (m1 profile, m2 evidence schemas, m3 trust boundary, m4 collector
  framework, m5 collector implementations, m10 orchestrator wiring,
  m12 risk-scored readiness). They are already tagged on the default
  branch and should be treated as immovable inputs.
- M40 (`result_json_bauto`) is on the critical path for the
  bmad-auto contract; M41/M42/M43 cannot land before it, and Wave 2
  bridges that emit results (M45, M47) inherit the same constraint.
- M36 (kernel schema) is the most-depended-on Wave 1 row; it should
  be drafted first inside Wave 1 in parallel with M25.

## How to drive (sw or equivalent)

The expected execution loop for each milestone, lifted from the
gate-roadmap convention so the same `sw run` discipline applies here:

1. **Pick the row.** Read the corresponding plan file under
   `docs/superpowers/plans/`. If the plan file does not yet exist,
   author it first using the gate-roadmap plan template (one H1, then
   `## Why`, `## What`, `## Tests`, `## Risks`, `## Out of scope`). Do
   not skip the plan step even for sub-300-LOC milestones.
2. **Open a feature branch.** `git switch -c bma-d/compat-mNN-<slug>`
   off the current default branch. The branch name MUST match the row
   slug; `install.sh`, smoke tests, and the tag prefix all key off it.
3. **TDD, one module at a time.** For each owner module listed in the
   row:
   a. Add a failing test under `tests/test_<module>.py` that exercises
      the smallest meaningful contract surface.
   b. Run only that test:
      `PYTHONPATH=skills/bmad-story-automator/src python3 -m unittest tests.test_<module>`
      and confirm it fails for the expected reason.
   c. Write the implementation under
      `skills/bmad-story-automator/src/story_automator/core/<module>.py`
      (or `commands/`, `adapters/`, `data/` as the row dictates), with
      `from __future__ import annotations` at the top, stdlib +
      `filelock` + `psutil` only, and `<= 500` LOC per file.
   d. Rerun the same test, confirm pass, then expand coverage.
4. **Full-suite gate.** Before staging, run the full suite from the
   repo root:
   `PYTHONPATH=skills/bmad-story-automator/src python3 -m unittest discover -s tests`.
   Baseline is 3124 tests passing as of 2026-06-20; the new milestone
   must keep that baseline green and add at least one new test per
   owner module. Then run `npm run verify` so `test:python`,
   `pack:dry-run`, `test:cli`, and `test:smoke` all pass on the same
   tree.
5. **Guardrail review.** Confirm `git diff` does not touch
   `skills/bmad-story-automator/src/story_automator/core/telemetry_events.py`,
   does not add an import outside the stdlib + `filelock` + `psutil`
   allow-list, does not introduce trailing whitespace or
   whitespace-only churn, and does not delete or re-date any historic
   changelog entry. The smoke-test harness already enforces the npm
   packaging side; the Python guardrails are on the author.
6. **Commit + trailer.** One commit per logical step, conventional
   commit subject (`feat(compat-mNN): ...`, `fix(compat-mNN): ...`,
   `test(compat-mNN): ...`, `docs(compat-mNN): ...`), and every commit
   carries the trailer
   `Generated-By: claude-opus-4-7`. Never use `--no-verify`, never
   amend a previously pushed commit, never force-push to the default
   branch.
7. **Changelog entry.** Add a dated entry under `docs/changelog/`
   using the closed four-tag vocabulary
   (`[FULL]` / `[LITE]` / `[SKELETON]` / `[DEFERRED]`) per M11. New
   milestones almost always tag `[FULL]`; thin shims or
   contract-only milestones may tag `[LITE]`.
8. **Tag the milestone.** After merge to the default branch, push an
   annotated tag `compat-mNN-<slug>` pointing at the merge commit.
   Update the row's `Status` column in this file to `tagged` in the
   same commit that pushes the tag (a docs-only follow-up commit is
   acceptable, but the row MUST be updated before starting the next
   milestone in the same wave).
9. **Roll forward.** Re-read the dependency graph above before
   starting the next row; if a parent slipped, surface that on the
   roadmap by flipping the dependent row(s) to `deferred` rather than
   silently working ahead.

If `sw` (superpowers workflow) is the active driver, the equivalent
invocation is `sw run compat-mNN-<slug>` from the repo root; `sw` will
honor the plan-file path conventions, branch naming, tag prefix, and
the `Generated-By` trailer automatically. If `sw` is unavailable, the
nine steps above are the manual fallback and produce a byte-identical
result on the default branch.
