# Spec Review — Milestone A — End-to-End Factory Self-Evaluation Harness

> Date: 2026-06-22 · Reviewer: adversarial gap-analysis pass · Status: **enhancements applied** (5 HIGH gaps resolved inline in spec/plan; MED/LOW tracked in spec §Tracked enhancements)

## TL;DR

The harness is conceptually sound — a consumer-only integration test that drives `run_production_gate` against the factory's own tree is exactly the regression net the codebase is missing. But the spec has at least one **showstopper bug** (the `audit_policy` shape it documents does not match `audit_for_policy`'s contract — `{"enabled": True, "path": ...}` will silently disable audit, so `audit_chain_verifies` will assert against an empty/missing file), several **schema-truth gaps** (no required `tier` argument documented for `run_production_gate`, `target` shape under-specified, profile-hash assertion path correct only by coincidence), and many under-specified edge cases (concurrency lock, BMAD_AUDIT_KEY restore order, AuditLockTimeout, FAIL-closed default verdict with the bundled profile, audit-floor sentinel for `tests/integration/`, ruff scope, Windows path math, smoke-test packaging exclude). The plan is structurally fine but inherits every spec defect because Task 2.2 transcribes them verbatim. Before implementation, the spec MUST fix the `audit_policy` key, name the missing `run_production_gate` kwargs, replace the brittle profile-hash assertion path with the actual location verdict_engine writes to, and either add `categories_na: ["*"]` or assert FAIL as the expected empty-registry verdict (since the bundled default profile activates every category and fail-closed will pin it to FAIL). Plan needs a deterministic env-restore protocol in tearDownClass and an explicit audit-floor sentinel registration as a follow-up tag.

Total findings: **23** (5 HIGH, 11 MED, 7 LOW).

## Findings table (sorted: HIGH first)

| ID | Section | Severity | Issue | Suggested patch |
|---|---|---|---|---|
| A-01 | spec §Design / setUpClass step 7 | HIGH | `audit_policy = {"enabled": True, "path": str(audit_path)}` does NOT match the codebase contract; `audit_for_policy` reads `policy["security"]["audit_trail"]`. With the spec'd shape, `audit_for_policy` returns `None`, no audit log is ever appended, the file stays empty, and `test_audit_chain_verifies_after_gate` will assert `last_seq >= 1` against `(True, 0)` — guaranteed failure. | Replace with `audit_policy = {"security": {"audit_trail": True}}` to match `audit_for_policy` + every existing test fixture (`tests/test_gate_cmd.py:235`). |
| A-02 | spec §Design / hash assertion + plan Step 3.5 | HIGH | `test_profile_hash_recorded_on_gate_file` happens to work, but the spec asserts a brittle path (`gate_file["profile"]["hash"]`) that `validate_gate_file` does NOT enforce — `gate_file["profile"]` is "must be an object" only. Worse, the spec implies the profile dict on the gate file equals the input profile (it doesn't — verdict_engine rewrites it to `{"id": ..., "hash": ...}`). An implementer reading the spec literally will write `self.assertEqual(self.gate_file["profile"], self.profile)`, which will fail. | Pin the contract explicitly: "`gate_file['profile']['hash']` is set by `verdict_engine.evaluate_gate` and equals `compute_profile_hash(profile_at_input)`; do NOT assert equality on the full profile dict; the persisted `profile` sub-object holds `{id, hash}` only." |
| A-03 | spec §Design / setUpClass step 8 + plan Task 2.2 | HIGH | The `run_production_gate(...)` invocation in the spec is incomplete: missing `tier` kwarg semantics (defaults to `"code"` via `make_gate_file`), the `target` dict has no documented vocabulary check (existing fixtures use `{"kind": "story|repo", "id": ...}`), and `factory_version="milestone-a"` may not match `resolve_factory_version()` which is the production reuse-key contract — reuse-path test (Task 6.1) will succeed on the harness's hand-coded value but mask a real reuse-key drift bug. | Document that the harness intentionally bypasses `resolve_factory_version()` to keep the reuse-key deterministic across releases; add an explicit comment in the spec calling that out; and add `tier="code"` explicitly so future tier vocabulary changes don't silently drift the gate file. |
| A-04 | spec §Design / "Empty registry" rationale + plan Step 3.2 | HIGH | With an empty registry against `data/profiles/default.json`, every active category in `profile.categories.code` (correctness/static/security/license/observability/invariants/process) and `.system` (reliability/resilience/durable_hitl/blast_radius/cost_to_serve) has **no evidence**. `compute_all_verdicts` marks each as fail-closed with `rationale: "no evidence collected for active category ..."`, so `overall` is deterministically **FAIL**. The spec's "all four verdicts accepted" framing is technically true but hides this: the harness as written exercises ONLY the FAIL path, not PASS. Two real consequences: (i) any future change that flips empty-registry FAIL→CONCERNS goes undetected; (ii) the determinism/reuse test in Task 6.1 may interact with `fail_closed_triggered` markers we don't currently set but might add in m13+. | Either (a) set `profile["categories_na"] = sorted(all_active_cats)` for the test only, so the gate produces PASS and exercises a richer code path, OR (b) pin `gate_file["overall"] == "FAIL"` explicitly in a `test_empty_registry_fail_closed_verdict` so the FAIL semantics are a documented contract, not an accident. |
| A-05 | spec §Design / setUpClass step 7 + plan Step 2.3 | HIGH | `os.environ["BMAD_AUDIT_KEY"] = "milestone-a-test-secret"` is set with no documented save-and-restore protocol; tearDownClass only "restores prior value" but the spec doesn't say "do NOT restore the prior key when it was unset" (`os.environ["X"] = None` is a TypeError). More serious: if the test runner inherits an operator's real secret, our test-only secret silently overwrites it; if `tearDownClass` later fails before restoration, we leak the previous state. The audit-env scrub helper protects subprocess env; it does NOT protect the in-process operator key. | Add an explicit pattern (used in `tests/test_audit_call_sites.py:73`): `cls._saved = os.environ.pop("BMAD_AUDIT_KEY", None)` then in tearDownClass `os.environ.pop("BMAD_AUDIT_KEY", None); if cls._saved is not None: os.environ["BMAD_AUDIT_KEY"] = cls._saved`. Wrap the gate-call body in `try/finally` so restoration is unconditional. |
| A-06 | spec §Scope / Out-of-scope + §Verification | MED | The spec waives "add audit-floor invariant for tests/integration/" but never registers the parking-lot follow-up as a tracked deliverable. Without a sentinel, an empty `tests/integration/` directory could ship in a future commit and `discover -s tests` would still report 4070 — the regression net silently dies. | Add a follow-up tag (`milestone-a-audit-floor-sentinel`) to the parking lot with the exact invariant: "tests/integration/test_factory_self_evaluation.py exists and defines ≥ 1 `test_*` method" — file it as a separate planned commit before the milestone is "done". |
| A-07 | spec §Design / `cls.commit_sha` | MED | Plan Step 2.2 uses `cls.commit_sha[:12]` but the setUpClass pseudocode in the spec assigns the variable name `commit_sha` (no `cls.` prefix). The plan implicitly assumes an attribute that the spec never names. Implementer may write a local and then hit `AttributeError` in `cls.gate_id = ...`. | Spec must say `cls.commit_sha = subprocess.check_output(...).decode().strip()` explicitly, and pin "strip() the trailing newline — `rev-parse HEAD` emits `<sha>\n` and a stale newline poisons gate_id validation regex (`^[a-zA-Z0-9._-]+$`)". |
| A-08 | spec §Design / Skip semantics #4 | MED | `assert_host_context` raises `TrustBoundaryError`, not `SkipTest`. The spec's "setup catches the assertion and skips" implies a blanket except, but `TrustBoundaryError` extends `RuntimeError`. A broad `except RuntimeError` would swallow real wiring bugs (gate orchestrator emits `RuntimeError` in several places — e.g. lock timeouts, marker corruption). | Catch `TrustBoundaryError` specifically (importable from `core.trust_boundary`), not the parent class. Plan Step 2.2 needs the exact `from story_automator.core.trust_boundary import TrustBoundaryError` and `except TrustBoundaryError:` clause. |
| A-09 | spec §Risks table + plan Task 6.1 | MED | `test_second_invocation_returns_reused_gate_file` does NOT exercise the reuse path it claims. `check_gate_reuse` matches on `(commit_sha, profile_hash, factory_version)` AND requires the gate file to be **persisted** under `_bmad/gate/verdicts/`. The first run inside an isolated `cls.project_root` writes the file there; the second run inside the same temp dir reuses it — so far so good. But the test name reads "returns reused gate file" while the assertion only checks `gate_id` and `evidence_merkle_root`. A bug that re-runs collectors but returns a freshly-computed identical gate would silently pass. | Add a stronger assertion: mtime of `_bmad/gate/verdicts/<gate_id>.json` is unchanged across the two calls, OR mock `_run_collectors` and `assert_not_called()` on the second call. |
| A-10 | spec §Hard constraints / "Runtime budget ≤ 5s" | MED | No timeout enforcement. CI runners under load have hit 8–15 s for similar lifecycle tests in this repo. An empty-registry gate is fast, but `filelock` acquires with 3600 s timeout and HMAC chain key derivation runs HKDF — measured but not budgeted. If the runtime grows past 5 s no test fails, just a doc lie. | Either drop the 5 s budget claim, or wrap the setUpClass gate call with `time.monotonic()` and `cls.assertLess(elapsed, 5.0)` in a dedicated `test_runtime_budget_under_5s` method (skip on slow-CI label). |
| A-11 | spec §Design / `audit_path` semantics | MED | Spec passes `audit_path = project_root / "audit.jsonl"` as both a key in `audit_policy["path"]` AND as the `audit_path` kwarg to `run_production_gate`. Looking at the real signature, the orchestrator uses `audit_path` directly and ignores `audit_policy["path"]`; the docs encourage a redundant key that doesn't exist on any test fixture. After fixing A-01, the `"path"` key is also gone — but the spec must say so explicitly. | After fixing A-01, drop the `"path"` from `audit_policy` entirely; document "`audit_path` is the only path source; `audit_policy["security"]["audit_trail"]` is the only enable flag." |
| A-12 | spec §Verification / audit-floor sanity | MED | "24+ invariants" is unbounded above. If the integration harness happens to add an invariant (e.g. `tests/integration/__init__.py` docstring), the audit-floor count might change. The spec needs a precise expected count or "audit-floor count is ≥ 24 AND ≤ 25 — any deviation is reviewed". | Pin to "24 invariants, no new sentinels added or removed in this milestone; sentinel for tests/integration/ tracked as a separate audit-floor-sentinel commit per A-06." |
| A-13 | spec §Acceptance / behavioral | MED | "4070 → 4078" arithmetic assumes 0–2 skips, but step 8.1 says "8+ new". If `setUpClass` raises SkipTest, ALL test_* methods skip (unittest semantics) — so under-skip-of-class-skip is 8, not 2. The spec says "2 skipped allowed" but the skip cascade would be 8. | Replace with "4070 → 4078 PASSED + 0 skipped (env OK); OR 4070 + 0 PASSED + ≥8 skipped (env precondition failed) — never partial; never any FAIL." |
| A-14 | spec §Design / determinism caveats | MED | The Merkle root for an empty bundle is the sentinel `""`. A consecutive run-2 will also yield `""`. So `test_merkle_root_shape_64_hex_or_empty_sentinel` is permanently the empty branch under Milestone A's empty-registry choice — the 64-hex branch is dead code in this harness. That's documented, but the spec doesn't say a future change to the orchestrator (e.g. always emit a synthetic "gate-started" evidence record) would suddenly switch the branch. | Add a one-line note: "If Milestone B's first collector lands before this harness ships, the 64-hex branch becomes the live branch; the empty branch becomes the dead branch. Both must remain regex-valid in either direction." |
| A-15 | spec §Acceptance / quality gates | MED | `ruff check tests/integration/` is a subset of the existing `ruff check skills tests` lint step; running the subset adds nothing. Worse, `ruff format --check tests/integration/` (added in plan Step 7.1) is NOT enforced anywhere else in the repo today — introducing a `ruff format` check just for this dir is a divergent quality bar. | Drop the standalone subset commands; the existing `npm run lint:python` covers the new files. Do NOT introduce `ruff format` as a check unless the project ships it for all of `tests/` too. |
| A-16 | spec §Verification + plan Task 9 | MED | The spec mandates a single commit and Task 9.4 "archive workflow" markers, but never names the audit-floor invariant that catches a missing archive. If a future operator forgets to archive, nothing fails. | Either drop Task 9.4 (workflow archives are not part of the build contract for this milestone) or add a documented post-commit check in plan: `test -f .claude/workflows/<milestone>-archive.md || exit 1`. |
| A-17 | spec §Design / target shape | LOW | `target={"kind": "repo", "id": "bmad-story-automator"}` is not validated against `gate_schema.validate_gate_file`, which only checks `isinstance(target, dict)`. No closed vocabulary for `target.kind`. The harness picks an arbitrary string. | Document the de-facto vocabulary observed in tests (`story`, `repo`, `epic`) and state which one Milestone A picks and why; commit to the same shape for B/C/D so the regression net is consistent. |
| A-18 | spec §Hard constraints / "LOC budget ≤ 350" | LOW | The LOC table says "≤ 350 LOC across the two new files (soft 500 cap is the project ceiling)" but the harness wraps gate orchestration inside try/except SkipTest with restoration — non-trivial. 350 is tight; if the test surfaces 12 methods + setup/teardown + docstrings + the skip cascade, it'll be close. | Bump to 400; the project cap is 500 — there's slack. The 350 number is a habit, not a constraint. |
| A-19 | spec §Verification / branch hygiene | LOW | "Single commit on `bma-d/integration-all` with tag `compat-milestone-a`" — but the existing tag convention in this repo is `milestone-a-e2e-harness` (per plan Task 9.3). The spec and plan disagree on the tag name. | Reconcile: either `compat-milestone-a` or `milestone-a-e2e-harness`. The plan currently picks the latter; the spec verification step picks the former. Pick one. |
| A-20 | spec §Open questions / parking lot | LOW | Three parking-lot items exist but none have a tracking issue, commit, or planned milestone tag. Parking-lot items decay into forgotten work. | Either resolve here or open a tracking commit reference (e.g. "see future spec 2026-06-23-XX-evidence-merkle-presence.md") with a real placeholder. |
| A-21 | plan §Pre-requisites | LOW | "Branch is `bma-d/integration-all` and clean (`git status` empty)" — but our branch already has the four committed spec/plan files from HEAD 5424b7e. The pre-req is unreachable as written. | "`git status` shows only the four pending milestone-A files (or already clean if specs were committed in a prior step)". |
| A-22 | plan §Rollback / Hard rollback note | LOW | "Operator runs: `git reset --hard HEAD~1`" — would erase Milestone A's commit, but in `bma-d/integration-all` HEAD~1 is the spec/plan commit (5424b7e), which means the rollback drops the specs too. | Change to "git revert <sha>" only; specify "HARD reset is not used for this milestone". |
| A-23 | spec + plan / cross-platform | LOW | The spec mentions Windows git-bash and WSL as supported platforms ("quality gates portable") but the harness uses `Path` arithmetic + `subprocess.run("git rev-parse HEAD")`. On Windows-git-bash, line endings and `.exe` resolution can change `commit_sha` shape; on a worktree without HEAD, `rev-parse HEAD` exits with non-zero but writes a non-empty stderr. | Add a one-line note: "decode with `text=True` then `.strip()`; handle CalledProcessError AND empty stdout; treat empty as 'no git' and skip." |

## HIGH-severity findings

### A-01 — `audit_policy` shape is wrong (silent disable, test will FAIL)

**Location:** `docs/superpowers/specs/2026-06-22-e2e-factory-harness-design.md` §Design (setUpClass step 7), `docs/superpowers/plans/2026-06-22-e2e-factory-harness-plan.md` Task 2.2.

**Problem:** Spec/plan pseudocode constructs `audit_policy = {"enabled": True, "path": str(audit_path)}`. The codebase contract — `core/audit.py::audit_for_policy` and every existing test fixture (e.g. `tests/test_gate_cmd.py:235`) — uses `{"security": {"audit_trail": True}}`. With the spec's shape, `audit_for_policy` returns `None`, `emit_gate_audit` no-ops, the JSONL file is never created, and `AuditLog.verify()` returns `(True, 0)`. The harness's `test_audit_chain_verifies_after_gate` asserts `last_seq >= 1` — guaranteed FAIL on first implementation.

**Suggested patch:** Spec must say:
```
cls.audit_policy = {"security": {"audit_trail": True}}
cls.audit_path = cls.project_root / "audit.jsonl"
```
And remove every reference to `audit_policy["enabled"]` and `audit_policy["path"]`.

### A-02 — Profile-hash assertion path is correct by coincidence, but spec misleads

**Location:** Spec §Design "test_profile_hash_recorded" / Acceptance #5 + Plan Step 3.5.

**Problem:** `validate_gate_file` only requires `gate["profile"]` to be `isinstance(dict)` — no `hash` key requirement. The reason `gate_file["profile"]["hash"]` actually exists at runtime is `verdict_engine.evaluate_gate` rewrites the profile sub-object to `{"id": ..., "hash": ...}` at line 200–220. A reader of the spec who is unaware of that rewrite may (a) assert `gate_file["profile"] == self.profile` (will fail — the persisted form is a 2-key projection, not the full dict); (b) assume any future verdict-engine refactor that names the field `profile_hash` instead of `profile.hash` will be caught (it won't — the spec pinned the wrong contract).

**Suggested patch:** Add to spec §Design:
> The harness asserts on the **projection** that `verdict_engine.evaluate_gate` writes back into `gate_file["profile"]` (currently `{"id": <profile.id>, "hash": <compute_profile_hash(profile)>}`). Do not assert on the full input profile dict. If the projection schema changes, both this harness and `validate_gate_file` need a coordinated update.

### A-03 — `run_production_gate` call missing required+conventional kwargs

**Location:** Spec §Design / setUpClass step 8.

**Problem:** The actual signature (verified at `core/gate_orchestrator.py:439`) accepts `tier` via the gate-file factory but the spec example doesn't show it; `target` is documented loosely as `{"kind": "repo", "id": "bmad-story-automator"}` with no schema vocabulary check; `factory_version="milestone-a"` is hand-coded but production callers use `resolve_factory_version()` — the spec doesn't explain WHY the harness bypasses the production resolver. A naive implementer may "improve" the spec by switching to `resolve_factory_version()`, then watch the determinism test flap whenever the factory version constant ticks.

**Suggested patch:** Spec §Design should add a "call construction" subsection:
```
run_production_gate(
    cls.project_root,
    cls.gate_id,
    commit_sha=cls.commit_sha,
    target={"kind": "repo", "id": "bmad-story-automator"},  # closed-vocab "repo"
    profile=cls.profile,
    factory_version="milestone-a",  # deliberately hand-coded, NOT resolve_factory_version()
    registry=cls.registry,
    priority="P1",
    audit_policy=cls.audit_policy,
    audit_path=cls.audit_path,
    # tier, has_unmitigated_risk_9, waivers, lie_detector, fail_closed: defaults
)
```
and add a rationale paragraph: "the harness pins `factory_version` to a constant so determinism doesn't break when the production resolver is bumped."

### A-04 — Empty registry pins overall to FAIL on the bundled default profile

**Location:** Spec §Design "Empty-registry caveat" + Plan Step 3.2.

**Problem:** `data/profiles/default.json` defines 12 active categories across code+system and an empty `categories_na`. `verdict_engine.compute_all_verdicts` fail-closes any active category that has no evidence. With an empty registry, EVERY active category fail-closes; `aggregate_verdicts` returns FAIL. So the "all four verdicts in vocabulary" assertion is structurally tautological — only one verdict is reachable. Future operators reading the spec think the harness "exercises lifecycle" but it actually exercises one fail-closed path.

**Suggested patch (pick one):**

**Option A (cleaner — exercises PASS path):**
```
# in setUpClass, mutate a copy of the profile:
cls.profile = load_bundled_profile("default")
cls.profile["categories_na"] = sorted(
    sum(cls.profile.get("categories", {}).values(), [])
)
cls.profile_hash = compute_profile_hash(cls.profile)
```
And document: "the harness deliberately disables all active categories so the gate exercises the PASS lifecycle. Milestone B introduces a real collector and re-enables a single category."

**Option B (cleaner — pins fail-closed contract):**
Add a 9th `test_overall_is_fail_closed_with_empty_registry` method:
```
self.assertEqual(self.gate_file["overall"], "FAIL")
```
and document why. Replace the four-verdict membership check with this single-value assertion.

### A-05 — BMAD_AUDIT_KEY save/restore protocol is under-specified

**Location:** Spec §Design / step 7 + Plan Step 2.3.

**Problem:** The spec says "set BMAD_AUDIT_KEY in os.environ ... if not already set" — but the gate's HMAC chain key is **derived from** that value, so if the variable is "already set" the audit chain will be keyed off the operator's real secret. Then `tearDownClass` "deletes it from env" — leaking the operator's secret out of process scope. Conversely, if BMAD_AUDIT_KEY was unset before the test, "restore the prior value" becomes `os.environ["BMAD_AUDIT_KEY"] = None` which is a TypeError.

**Suggested patch:** Spec §Design should write the canonical pattern (already used by `tests/test_audit_call_sites.py:73`):
```
# setUpClass
cls._saved_audit_key = os.environ.pop("BMAD_AUDIT_KEY", None)
os.environ["BMAD_AUDIT_KEY"] = "milestone-a-test-secret"

# tearDownClass
os.environ.pop("BMAD_AUDIT_KEY", None)
if cls._saved_audit_key is not None:
    os.environ["BMAD_AUDIT_KEY"] = cls._saved_audit_key
```
And wrap the gate call in `try/finally` so the restoration runs even if the gate raises.

## MED-severity findings

See table above (A-06 … A-16). Each row is self-contained; defer to enhancement OR backlog.

## LOW-severity findings

See table above (A-17 … A-23). Each row is a polish item; backlog OK.

## Recommended enhancement to spec/plan (before implementation)

1. **Fix A-01** (audit_policy shape) — single-line spec edit; ALSO update plan Step 2.2 pseudocode.
2. **Resolve A-04** (empty-registry verdict) — pick Option A or B; either yields a non-tautological assertion. Recommend **Option A** (`categories_na` disables all categories → PASS) because it exercises the richer adjudicator path that downstream milestones B/C/D will use.
3. **Fix A-05** (env restore) — add canonical save/pop/restore pattern to spec §Design pseudocode and plan Step 2.2 / 2.3; wrap the gate call in `try/finally`.
4. **Disambiguate A-02** (profile-hash projection) — add a paragraph naming `verdict_engine.evaluate_gate`'s profile-rewrite behavior so the assertion is anchored to a deliberate contract.
5. **Pin A-03** (run_production_gate kwargs) — paste the literal call-construction example into the spec so the implementer doesn't ad-lib.
6. **Pin A-08** (TrustBoundaryError import) — add the exact except clause to plan Step 2.2.
7. **Strengthen A-09** (reuse-path test) — add an mtime check or `_run_collectors.assert_not_called()` mock so the test catches a real regression.
8. **Reconcile A-19** (tag naming) — pick one tag string for spec + plan.
9. **Resolve A-13** (skip-cascade accounting) — restate the expected count in skip-vs-pass branches.

Items 1, 2, 3, 5 are blockers for "ready-to-implement". Items 4, 6, 7, 8, 9 are strongly recommended; deferrable to a brief enhancement PR. MED/LOW items can land as inline polish during execution.

## Verdict: **needs-enhancement** → **enhancements applied (2026-06-22)**

Three HIGH findings (A-01, A-04, A-05) are showstoppers — the spec as written will produce a test that either fails on its own audit-chain assertion (A-01), exercises only one of four documented lifecycle verdicts (A-04), or leaks the operator's audit key into post-test process state (A-05). A-02 and A-03 are slightly softer (the test may "work" but the contract is mis-stated, so the regression net it provides is weaker than the spec implies). Once the four HIGH fixes are applied and a single coherent verdict path is chosen, this is ready to implement; the MED/LOW items can be folded into the same enhancement pass or addressed as inline review comments.

## Resolved (enhancements applied 2026-06-22)

All 5 HIGH-severity findings have been patched directly into `docs/superpowers/specs/2026-06-22-e2e-factory-harness-design.md` and `docs/superpowers/plans/2026-06-22-e2e-factory-harness-plan.md`:

- ~~**A-01**~~ — `audit_policy` shape corrected to `{"security": {"audit_trail": True}}` in spec §Design step 7 and plan Step 2.2. Path key dropped (A-11 also resolved).
- ~~**A-02**~~ — `test_profile_hash_recorded_on_gate_file` description now anchored to `verdict_engine.evaluate_gate`'s projection rewrite; full-profile equality explicitly forbidden in spec §Design test list and plan Step 3.5.
- ~~**A-03**~~ — Full `run_production_gate(...)` call construction inlined in spec §Design step 8 and plan Step 2.2 with `tier="code"` explicit and `factory_version="milestone-a"` rationale documented (deliberate hand-coded bypass of `resolve_factory_version()` for determinism).
- ~~**A-04**~~ — Option A applied: `profile["categories_na"]` disables all active categories so the empty-registry gate exercises the PASS lifecycle (not the only-FAIL-reachable lifecycle).
- ~~**A-05**~~ — Canonical save-pop-restore pattern for `BMAD_AUDIT_KEY` inlined in spec and plan; gate call wrapped in `try/finally` so restoration is unconditional.

MED + LOW gaps (A-06..A-23) are tracked in the new "Tracked enhancements" section appended to the spec; A-07 (commit_sha attribute naming), A-08 (`TrustBoundaryError` specific catch), A-09 (reuse-path stronger assertion), A-11 (audit_path sole path source), A-14 (Merkle branch flip note), A-19 (tag-name reconciliation pin to `milestone-a-e2e-harness`), A-22 (rollback uses `git revert` not hard reset), A-23 (subprocess decode + empty-stdout handling) are resolved inline as part of the HIGH patches; the rest are dispositioned as backlog or inline polish.
