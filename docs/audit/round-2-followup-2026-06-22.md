# Round-2 Bug Sweep — Post-Landing Follow-up

## TL;DR

Round-2 sweep shipped 11 bugfix commits but left an **uncommitted, incomplete twelfth fix** for an audit-key environment-leak vulnerability. The in-flight change broke 6 tests (4 module-size budget invariants from audit-floor + 2 test-pollution failures from a process-wide key cache that did not invalidate on missing env). I reverted the uncommitted change to restore the green suite; the security fix needs its own dedicated milestone with proper scoping.

After revert: **4,055 tests passing**, ruff clean, audit-floor invariants intact, working tree clean.

## What shipped (11 round-2 bugfixes)

Commits between `02a96c4` (L1 follow-up) and `7954bec` (round-2 report):

| # | Commit | Bug | Fix |
|---|---|---|---|
| 1 | `d7d58cf` | **A-01** — Collector evidence never carried metrics; security/correctness/mutation rules saw uniform zeros, making the L3 worst-of fix moot | Thread `parse_metrics` callback through `CollectorConfig` → `run_collector_with_timeout` → `make_evidence_record`. Adjudicator now populates real metric dicts from collector stdout. |
| 2 | `1942268` | **J-02** — L3 worst-of reducer accepted any value type silently; non-numeric/None entries crashed downstream rules | Validate metric values per-reducer; reject non-numeric/non-bool at the boundary with clear error. |
| 3 | `6f53d25` | **J-03** — L1 PID liveness check could miss PID-reuse via stale process | Composite-identity check: marker now records `pid + start_time` (psutil `Process.create_time`); recover_from_crash compares both. |
| 4 | `d1410a1` | **A-02** — `scalability` collector pointed to `scale_lint_check.py` and `capacity_plan_check.py` that did not exist on disk | Ship the missing scripts under `core/checks/`. |
| 5 | `3d5d1d1` | **J-04** — Session state loader could not distinguish corrupt JSON from absent file | Raise `SessionStateCorruptedError` on corrupt; return None on absent; callers route correctly. |
| 6 | `ca753a5` | **E-01 + E-02** — Merkle ledger leaf hashes vulnerable to CVE-2012-2459 (second-preimage when leaf count is odd) | RFC 6962 domain-separation: leaf prefix `0x00`, internal-node prefix `0x01`. Reproducer + golden roots updated. |
| 7 | `c9cc0f8` | **A-04 + G7** — `create_collector_checkout` accepted refnames (`HEAD`, branches, tags) and short SHAs as `commit_sha`, then failed the prefix-match SHA mismatch guard | Require full 40-hex SHA at the boundary; refnames raise `CollectorCheckoutError("commit_sha must be 40-hex")` with a clear remediation message |
| 8 | `922c87c` | **G1 + G2** — `tmux capture-pane` decode could crash on non-UTF8 stdout | Broaden the catch to `UnicodeDecodeError` and fall back to replace-mode decoding with a flagged finding. |
| 9 | `269eca0` | **LENS-H-01 + E-09** — `MerkleLedger.append` was not crash-safe; concurrent append could corrupt chain | Filelock + fsync the WAL on every append; chain re-validates on next start. |
| 10 | `3e66ced` | **LD-01 + LD-12** — `risk_to_story` close-tag matching was case-sensitive; malformed blocks produced silent data loss | Case-insensitive close-tag regex; malformed-block guard raises with file:line in error message. |
| 11 | `1b09d09` | **LENS-C-01** — `commands.tmux` `name` action ignored `--cycle` flag | Parse `--cycle` properly in argparse; tests cover both presence and absence. |

## What was reverted (incomplete D-04 fix)

**Bug D-04 — audit-key visible to subprocesses via os.environ:**

The in-flight (uncommitted) work added:
- `_cached_key`, `_cached_raw_digest` module-level cache in `core/audit.py`
- `_reset_key_cache()` helper for tests
- A `load_key_from_env()` rewrite that pops `BMAD_AUDIT_KEY` from `os.environ` after first read so subprocesses cannot inherit it

**Why reverted:**
1. The change added 47 lines to `core/audit.py`, pushing it from 478 → 517 LOC, breaking **four audit-floor invariant tests** (`AuditModuleSizeBudgetTests`, `AuditModuleSizeBudgetM2/M3/M4Tests`) that pin the 500-LOC ceiling.
2. The process-wide cache did not invalidate when the env var was later unset. `load_key_from_env(env={})` returned the previously-cached key instead of None, breaking `LoadKeyFromEnvAbsentContractTests` and `AuditVerifyCmdKeyMissingTests`.
3. Both failures only manifest under full-suite test ordering — running the affected tests alone passed, hiding the regression from a partial-suite check.

**What a correct D-04 fix needs:**
1. Move the cache + pop logic into a sibling module (e.g. `core/audit_key_cache.py`) to keep audit.py under 500 LOC.
2. Make the cache observe env state on every call: if the env var disappears, invalidate the cache.
3. Add explicit cache-reset hooks the test fixtures can call between cases to avoid test pollution.
4. Ship the corresponding subprocess-env-scrubbing test that exercises the actual threat model (a Popen child inheriting the env should NOT see `BMAD_AUDIT_KEY`).

**Recommendation:** ship D-04 as a dedicated milestone (`compat-secfix-D-04-audit-key-env-scrub`) with the four discipline items above, not as a tail-end commit on the round-2 sweep.

## Final state after revert

| Metric | Value |
|---|---|
| HEAD | (latest commit after this report lands) |
| Branch | `bma-d/integration-all` |
| Tests | **4,055 passing**, 2 skipped, 0 failures, 0 errors |
| Ruff | All checks passed |
| audit.py LOC | 478 (under 500 budget) |
| Audit-floor invariants | 17/17 green |
| Working tree | clean |

## Process lessons

- **Full-suite gating must happen before commit, not after.** The round-2 workflow agent that drafted D-04 ran a targeted test for its new behavior but did not re-run the full suite before staging — so the audit-floor module-size budget regression slipped past local verification.
- **Module size budget tests are load-bearing audit-floor invariants.** Several of them target the same `core/audit.py` LOC count from different test files; that triplication catches the cross-platform/cross-installation case where one module-size test runs but another does not.
- **Process-wide caches must invalidate when the source they cache disappears.** A cache keyed by "is the env var set" must re-check that every call, not just on first set. This is a common bug pattern worth a project-wide grep for similar shapes.

## Recommended follow-up

1. **Ship D-04 properly** as its own milestone with the four discipline items above (highest priority — it is a real defensive-depth security fix).
2. **Add a `_reset_*_cache()` audit** across the codebase — find every module-level cache and confirm it has both a reset hook and an invalidation contract.
3. **Module-size budget as ruff custom rule** — these are currently expressed as runtime tests, but a ruff plugin (or a pre-commit hook) would catch them at the seam instead of during the full suite.
