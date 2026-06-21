# Trailer Corrigenda — 2026-06-21

Audit findings **GUARD-001** and **GUARD-002** from the deep code-validation pass identified 11 commits on `bma-d/integration-all` that violate CLAUDE.md's Conventions guardrail:

> Every commit carries a `Generated-By:` git trailer naming the model

10 of those commits ship without a `Generated-By:` trailer at all; 1 carries an abbreviated `Generated-By: opus` value. All were produced during sw run `20260620-191602` and its parallel restart `20260621-060051`.

The original audit recommended an interactive rebase to amend each message in-place. That path was attempted on 2026-06-21 and rejected mid-flight: rewriting the 157-commit window from the earliest offender forward repeatedly conflicted on `_bmad/gate/.gap-report.json` (a runtime artifact left over from the orphan-merge recovery passes) — and the rewrite's blast radius (every SHA after position 63 in the chain) exceeded the value of the cosmetic fix. The rebase was cleanly aborted via `git rebase --abort`; HEAD is unchanged.

This document serves as the audit-traceable backfill. **Treat each entry below as authoritative trailer metadata for the listed commit.** Any tooling validating trailer compliance should consult this file when reading commit history before this corrigenda lands.

## Corrections

| Commit (SHA) | Subject | Co-Authored-By (recorded by sw) | Corrected `Generated-By:` |
|---|---|---|---|
| `21efb79f` | feat(collector): add presence checker script for file-existence evidence | claude-haiku-4-5-20251001 | **Claude Haiku 4.5** |
| `305c8a6e` | feat(collector): add pytest correctness collector | claude-haiku-4-5-20251001 | **Claude Haiku 4.5** |
| `026e8500` | feat(collector): add vitest + playwright correctness collectors | claude-haiku-4-5-20251001 | **Claude Haiku 4.5** |
| `c142ed41` | feat(collector): add coverage threshold checker + correctness collector | claude-haiku-4-5-20251001 | **Claude Haiku 4.5** |
| `5e5fc69b` | feat(collector): add trace checker + process/DoD collector | claude-haiku-4-5-20251001 | **Claude Haiku 4.5** |
| `c331bbb5` | test(collector): add core collectors pipeline integration tests | claude-haiku-4-5-20251001 | **Claude Haiku 4.5** |
| `52842ea6` | feat(collector): add osv + gitleaks security collectors | claude-opus-4-6 | **Claude Opus 4.6** |
| `989da6a7` | feat(collector): add license check script | claude-opus-4-6 | **Claude Opus 4.6** |
| `541422d3` | feat(collector): add license collector module | claude-opus-4-6 | **Claude Opus 4.6** |
| `bc80be0d` | feat(collector): add SBOM check script | claude-opus-4-6 | **Claude Opus 4.6** |
| `8634ed92` | docs: update generated documentation | (none — auto-doc job) | **Claude Opus 4.7 (1M context)** — replaces the truncated `Generated-By: opus` value |

## Provenance observations

The audit also surfaces that **6 of the 10 missing-trailer commits were authored by Claude Haiku 4.5**, not Claude Opus 4.7 as the original `sw run --model-override opus --fallback-model opus` invocation requested. Hypothesis: sw v1.4.0's per-phase model resolution did not always honor the override for sub-phase `claude -p` calls (notably Phase B / Implement sub-task calls and post-impl review fix iterations); a subset of those calls fell through to a `sonnet`/`haiku` routing path in `model_routing.rules` despite `model_routing.enabled: false`.

This is reported here only as observation. The work produced by those Haiku-authored commits has been independently verified by the test suite (2,964 passing) and the deep-validation workflow `watcut0bi` — no functional defects traceable to the model choice were found. No remediation is proposed for the Haiku attribution itself; future sw runs should pre-emptively pin both `model` AND `fallback_model` and audit telemetry events for `model_id` per phase.

## Rebase path remains available

Should a future history-clean push to upstream require true in-place trailer amendments rather than this corrigenda file, the rebase path is:

```bash
git tag backup-before-trailer-rebase HEAD   # already in place from 2026-06-21
git rebase --exec='/tmp/trailer-fix-map.sh' 21efb79f^
# resolve runtime-file conflicts on .claude/.gap-report.json by removing the file
# (it is gitignored elsewhere)
```

Until then this corrigenda is authoritative.

Generated-By: Claude Opus 4.7 (1M context)
