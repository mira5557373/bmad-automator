# Milestone A — End-to-End Factory Self-Evaluation Harness — Design Spec

> Date: 2026-06-22 · Status: **Draft for review** · Topic: drive the production-readiness gate against the factory's own codebase, end-to-end, in a single integration test that exercises every wiring layer we've shipped (profile load, collector registry, trust boundary, orchestrator lifecycle, evidence I/O, Merkle export, audit chain).
> Provenance: written after Path B closed (`compat-path-b-complete`) and the round-2 audit landed (D-04 + 11 additional fixes). At 4070 tests / 24-invariant audit-floor we have unit and per-module coverage but **no single test exercises the full gate against a real target**. This spec installs that test as Milestone A.

## Goal

Add a single, self-contained `tests/integration/test_factory_self_evaluation.py` that points `run_production_gate` at the factory's own working tree — using the bundled `data/profiles/default.json` profile — and asserts the gate completes, returns a structured verdict, persists a non-empty evidence bundle with a 64-hex `evidence_merkle_root`, and produces a hash-chained audit log that `AuditLog.verify()` confirms is intact.

The harness is the first place we close the loop end-to-end. Everything downstream of Milestone A (B = curated bundled profile tuning, C = system-altitude smoke, D = soak/operator runbook) consumes its output. It is also the first regression net for cross-cutting wiring breaks: a profile/collector/audit drift that slips past every unit suite still has to make this test green.

## Scope

### In-scope
- New file `tests/integration/test_factory_self_evaluation.py`.
- New empty package marker `tests/integration/__init__.py` (so `unittest discover` picks the directory up).
- Use of existing public APIs only: `run_production_gate`, `CollectorRegistry`, `load_bundled_profile`, `compute_profile_hash`, `AuditLog`, `load_key_from_env`, `compute_evidence_bundle_merkle_root`, `load_evidence_bundle`, `load_gate_file`.
- Bundled `data/profiles/default.json` as the profile under test (no fork, no overlay).
- A skip path when the host lacks the environment to run the gate cleanly (no `git` binary, detached worktree with no HEAD, `BMAD_AUDIT_KEY` unsettable, sandbox where `psutil` cannot fork). The skip MUST be explicit (`self.skipTest`) with a single-sentence reason — never a silent green.
- Tests count toward audit-floor; harness asserts NO new module imports beyond what's already in the `core` allowlist.

### Out-of-scope
- New collectors, new categories, new verdict logic. The harness *consumes* what exists.
- Modifying `core/telemetry_events.py` (M01 owns it).
- Touching any frozen-gate-surface symbol (`docs/spec/frozen-gate-surface.md`).
- Adjudicator threshold tuning — that's Milestone B.
- System-altitude (per-epic) gate exercise — that's Milestone C.
- Operator-facing runbook / soak summary — that's Milestone D.
- Any change under `skills/bmad-story-automator/src/story_automator/` beyond test wiring. **The harness is pure consumer.** If a wiring bug surfaces, it is filed as a follow-up and addressed in a separate milestone (B/C/D or a focused fix commit).
- New Python dependencies. (`stdlib + filelock + psutil` only — guardrail.)

## Design

### Public API additions

**None.** The harness is a test-only consumer. The full surface it uses is already public and stable:

| Symbol | Module | Used as |
|---|---|---|
| `load_bundled_profile` | `core.product_profile` | Load `default.json` → `dict[str, Any]`. |
| `compute_profile_hash` | `core.product_profile` | Pin the profile hash for assertion + drift baseline. |
| `CollectorRegistry` | `core.collector_registry` | Empty registry (no collectors registered) — exercises the orchestrator-lifecycle wiring with the simplest possible registry. |
| `run_production_gate` | `core.gate_orchestrator` | Drive the full lifecycle. |
| `load_gate_file`, `load_evidence_bundle`, `compute_evidence_bundle_merkle_root` | `core.evidence_io` | Read back what the orchestrator persisted. |
| `AuditLog`, `load_key_from_env` | `core.audit` | Verify the hash chain. |
| `assert_host_context` | `core.trust_boundary` | (Implicit — `run_production_gate` calls it; the test runs on host so the call succeeds.) |

A second, optional read-back of the gate file via `load_gate_file` exists *for documentation*: the orchestrator already returns the gate file from `run_production_gate`, but reading the persisted file proves the disk artifact matches.

### File inventory

**New files (2):**
- `tests/integration/__init__.py` — empty package marker (one line: `"""Integration tests for the gate harness."""`).
- `tests/integration/test_factory_self_evaluation.py` — the harness itself (target 200–300 LOC; soft cap 500 per project guardrail).

**Modified files: none.** The plan-level discipline is "consumer-only". If a real wiring bug surfaces during implementation, it is logged in `notes` and shipped as a separate follow-up commit; this spec does not pre-authorize edits outside `tests/integration/`.

### Hard constraints

| Constraint | Budget |
|---|---|
| New deps | 0 (stdlib + filelock + psutil only — already used by gate orchestrator). |
| LOC budget | ≤ 350 LOC across the two new files (soft 500 cap is the project ceiling). |
| Frozen-gate-surface symbols touched | 0 (`docs/spec/frozen-gate-surface.md` unchanged). |
| Changes to `core/telemetry_events.py` | None. |
| New imports added to any existing module | None. |
| New audit-floor invariants needed | 0 to ship; if the integration tree grows we may add a sentinel "integration tests live under tests/integration/" invariant in a follow-up (out of scope here). |
| Runtime budget (single run, no real collectors) | ≤ 5 seconds on a stock CI runner. |
| Determinism | Two consecutive runs against an unchanged tree MUST produce the same gate_id, profile hash, Merkle root, and audit `(ok=True, seq>=1)` outcome. |

### Harness flow (single `TestCase`, multiple `test_*` methods)

The class is structured so each assertion is its own `test_*` method (driven from a shared setup that runs the gate exactly once). This gives focused failures in CI and makes the skip path trivial: the setup raises `unittest.SkipTest` if any precondition fails.

```
setUpClass:
    1. resolve repo_root = Path(__file__).resolve().parents[2]
    2. detect HEAD commit:
         try: commit_sha = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo_root)
         except (FileNotFoundError, CalledProcessError): raise SkipTest("no git or no HEAD")
    3. set up an isolated temp dir TMP, copy nothing — the gate writes its artifacts under
       repo_root by default; use a side dir to keep CI clean:
         project_root = TMP / "factory-self-eval"
         project_root.mkdir(parents=True)
    4. profile = load_bundled_profile("default")
       profile_hash = compute_profile_hash(profile)
    5. registry = CollectorRegistry()   # empty — fastest possible gate
    6. gate_id = "factory-self-eval-" + commit_sha[:12]   # deterministic
    7. set BMAD_AUDIT_KEY in os.environ (a fixed test-only secret) if not already set
       audit_path = project_root / "audit.jsonl"
       audit_policy = {"enabled": True, "path": str(audit_path)}
    8. run_production_gate(
         project_root, gate_id,
         commit_sha=commit_sha, target={"kind": "repo", "id": "bmad-story-automator"},
         profile=profile, factory_version="milestone-a",
         registry=registry, priority="P1",
         audit_policy=audit_policy, audit_path=audit_path,
       )
       store gate_file on cls.

test_gate_returned_dict       : isinstance(gate_file, dict)
test_overall_in_vocabulary    : gate_file["overall"] ∈ {PASS, CONCERNS, FAIL, WAIVED}
test_gate_id_round_trip       : load_gate_file(project_root, gate_id)["gate_id"] == gate_id
test_evidence_bundle_present  : load_evidence_bundle(...) returns non-None (may be empty dict for the empty-registry case → the test asserts "key exists in gate_file" instead of requiring records; we document why)
test_merkle_root_is_64_hex    : when bundle is non-empty, gate_file["evidence_merkle_root"] matches r"^[0-9a-f]{64}$"; when bundle is empty, root == "" (sentinel)
test_audit_chain_verifies     : AuditLog(audit_path, key=load_key_from_env()).verify() == (True, n) with n >= 1
test_profile_hash_recorded    : gate_file["profile"]["hash"] == profile_hash
test_determinism_second_run   : invoking run_production_gate again with same args returns the same gate_file (reuse path).
```

#### Empty-registry caveat

With `CollectorRegistry()` containing zero collectors, the gate has no evidence to collect. That is intentional for Milestone A: the goal is to prove the **lifecycle wiring** works, not to grade the codebase. The Merkle-root sentinel (`""` when bundle empty, 64-hex when non-empty) is precisely the contract we exercise. Milestone B introduces a *curated* registry that runs at least one real collector (ruff/static) against the factory; that becomes the first acceptance criterion that requires a non-empty bundle.

If the orchestrator's contract changes such that an empty registry no longer produces an empty bundle, Milestone A's test still passes (the regex covers either branch) — but Milestone B will need to update its acceptance.

### Skip semantics

The test is allowed to skip — and only skip — when:
1. `git` is not on PATH (or `git rev-parse HEAD` exits non-zero).
2. `BMAD_AUDIT_KEY` cannot be set (read-only env, e.g. some sandboxes).
3. `psutil` cannot start a subprocess (sandboxed CI sometimes denies fork).
4. `assert_host_context` raises (test invoked from inside a tmux child by mistake).

Each skip raises `unittest.SkipTest("<one-sentence reason>")`. The harness MUST NOT swallow other exceptions; any other failure is a real bug.

### Why this design

- **Empty registry is the safest first step.** It exercises every wiring seam (profile load, marker write/clear, audit emit, Merkle export, gate-file persistence) without depending on any tool being installed in CI. Milestone B will *add* a real collector; Milestone A just proves the loop closes.
- **One gate run, many assertions.** Running the gate inside each `test_*` would slow CI and pollute audit-floor. The `setUpClass` runs it once and the asserts are O(1) reads.
- **Determinism doubles as crash-recovery test.** A second `run_production_gate` call with the same `gate_id` exercises the reuse path; if reuse breaks (profile drift, Merkle drift, lock misuse), the second-run test fails loudly.
- **`tests/integration/` is the future home of B/C/D harnesses.** Creating it now (with an `__init__.py`) means subsequent milestones just drop a file in.

## Acceptance criteria

### Behavioral

- `python -m unittest discover -s tests -p 'test_factory_self_evaluation.py' -v` returns success.
- `python -m unittest discover -s tests/integration -p 'test_*.py' -v` returns success and includes the harness.
- The full suite (`npm run verify` → `test:python`) goes from 4070 to ≥ 4078 tests passing (8+ new assertions in 8+ `test_*` methods); 2 skipped allowed if precondition gates fire.
- If preconditions hold, the harness runs end-to-end in ≤ 5 s on a stock CI runner.
- If preconditions do not hold, the harness skips cleanly with a single explicit `SkipTest` raise; no other failure modes are tolerated.

### Test coverage

Minimum **8** new `test_*` methods on a single `TestFactorySelfEvaluation(unittest.TestCase)`:

1. `test_gate_returns_dict`
2. `test_overall_verdict_in_closed_vocabulary`
3. `test_gate_id_round_trips_through_load_gate_file`
4. `test_profile_hash_recorded_on_gate_file`
5. `test_merkle_root_shape_64_hex_or_empty_sentinel`
6. `test_audit_chain_verifies_after_gate`
7. `test_second_invocation_returns_reused_gate_file`
8. `test_gate_file_carries_factory_version`

(Plus optional `test_evidence_bundle_loads_without_error` if total LOC permits without exceeding the 350-LOC cap.)

### Quality gates

- `ruff check tests/integration/` is clean.
- `python -m unittest tests.test_audit_regression` remains at **24+** invariants and green (we add a sentinel later; not in this milestone).
- Full `python -m unittest discover -s tests` green; no flakes across 3 consecutive runs.
- `npm run verify` green.
- No file in `skills/bmad-story-automator/src/` modified.
- No new imports in any module under `core/` or `commands/`.
- Commit conforms to Conventional Commits + `Generated-By:` + `Co-Authored-By:` trailers.

## Risks + mitigations

| Risk | Likelihood | Mitigation |
|---|---|---|
| `assert_host_context` rejects the test runner (tmux session etc.) | Low | Setup catches the assertion and skips with a clear reason. |
| `BMAD_AUDIT_KEY` is not settable in some CI sandbox | Low | Setup detects via `os.environ` write-then-read and skips if unsettable. |
| Empty registry path produces an unexpected verdict | Low | Spec accepts the full `{PASS,CONCERNS,FAIL,WAIVED}` vocabulary — adjudicator's behavior for an empty evidence set is *its* contract, the harness just asserts membership. |
| Test introduces non-determinism via timestamps | Med | All assertions are over hashes / fixed strings / regex shapes; we never compare timestamps. The reuse-path test exercises determinism explicitly. |
| Audit chain key leaks into logs | Med | `BMAD_AUDIT_KEY` is set to a fixed test-only value; setup deletes it from env in `tearDownClass`. The audit module's existing scrub helpers prevent it from reaching subprocess env. |
| Future profile change invalidates the pinned hash | Low | The test computes `profile_hash` from the loaded profile at runtime; it does not pin a hex literal. (The spec records this explicitly to forestall a future "let's pin the hash literal" PR.) |
| Wiring bug found during implementation derails milestone | Med | Per scope, any wiring fix lands as a separate commit (and a fix-milestone), not inside this milestone's commit. The harness is *consumer-only*. |
| `tests/integration/` collides with collection if a parent test runner expects a flat layout | Low | We verified `unittest discover -s tests` already walks subpackages; the new `__init__.py` makes it explicit. Smoke check is part of acceptance. |

## Verification strategy

1. **Local TDD loop (per task, see plan):**
   - Add the failing test first.
   - Run `PYTHONPATH=skills/bmad-story-automator/src python -m unittest tests.integration.test_factory_self_evaluation -v`.
   - Add minimal harness scaffolding until it passes.
   - Repeat per `test_*` method.

2. **Full-suite regression:**
   - `python -m unittest discover -s tests -v` → 4078+ passing, 2 skipped baseline preserved.
   - `python -m unittest tests.test_audit_regression -v` → 24+ invariants green.

3. **Lint + pack + smoke:**
   - `ruff check tests/integration/` clean.
   - `npm run verify` end-to-end green.

4. **Determinism check (manual, once):**
   - Run the harness twice in succession on the same HEAD; eyeball gate_id and Merkle root are identical, and reuse-path test in run 2 fires (no second collector pass).

5. **Audit-floor sanity:**
   - `python -m unittest tests.test_audit_regression` confirms no AST/import/string invariants regressed.

6. **Branch hygiene:**
   - Single commit on `bma-d/integration-all` with tag `compat-milestone-a` (and any reserved follow-up tag space documented in the plan).
   - No `--no-verify`, no `--amend`, no force-push.

---

## Open questions / parking lot

- Should the harness assert `gate_file["evidence_merkle_root"]` is **always** present (even as `""`)? Current spec says yes — flagged for review.
- Do we want a CLI smoke alongside the unittest harness (`story-automator gate --self-eval`)? **Deferred to Milestone D** (operator UX).
- Should the integration test run under a feature flag (`BMAD_INTEGRATION_TESTS=1`) instead of always-on? **No** — keeping it always-on is the regression net we want; the skip path is the escape valve.

---

*This spec authorizes ONLY the work described in §Scope. Any wiring bug discovered during execution must be logged and shipped as a separate, scoped commit — Milestone A's PR stays consumer-only.*
