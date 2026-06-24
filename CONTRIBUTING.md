# Contributing

## Scope

This repository packages the BMAD story-automator workflow payload plus the Python runtime used by the installed workflow.

## Before Opening A PR

- keep changes scoped; avoid unrelated cleanup
- keep files under roughly 500 LOC when practical
- preserve pure skill install behavior under `.claude/skills`
- treat old `_bmad/bmm` story-automator install paths as migration-only backups
- avoid adding dependencies unless clearly justified
- run:
  - `npm run pack:dry-run`
  - `npm run test:smoke`
  - `PYTHONPATH=skills/bmad-story-automator/src python3 -m story_automator --help`
  - `python scripts/verify_retraction_format.py`

The `python scripts/verify_retraction_format.py` gate is expected to exit 0 on a clean tree; a non-zero exit indicates a malformed `### Retractions` bullet under `docs/changelog/` that must be fixed before opening the PR.

## PR Notes

- use Conventional Commits
- describe user-facing behavior changes
- mention install-path or workflow-path changes explicitly
- call out any payload or runtime files copied from upstream BMAD sources

## Changelog Scope Tags

Every new entry under `docs/changelog/` must carry exactly one scope tag from this closed four-tag vocabulary: FULL, LITE, SKELETON, or DEFERRED. The tag goes inside square brackets immediately after the timestamp and the hyphen on the entry's heading line, for example:

```text
## 260519-12:00:00 - [FULL] Title goes here
```

For entries without a time component the same rule applies after the bare date:

```text
## 260519 - [FULL] Title goes here
```

Exactly one tag is required per entry. PRs that add a changelog entry with no tag, with more than one tag, or with any tag string other than the four listed above must be rejected at review time. Tags apply only to the dated entry headings (level-two or level-three Markdown headings that begin with a six-digit date). Sub-section headings inside an entry such as `### Summary`, `### Added`, `### Changed`, `### Fixed`, `### Removed`, `### Files`, and `### QA Notes` must not carry tags.

The four tags mean:

- `FULL` — a change shipped with spec, implementation, tests, and verification all complete and passing every quality gate at merge time.
- `LITE` — a change shipped with implementation and tests but with reduced spec depth or deferred non-blocking polish, where every quality gate still passes at merge time.
- `SKELETON` — a change that lands structure or scaffolding only (for example a module stub or a directory tree) with no behavioral wiring and no test coverage requirement beyond import compilation.
- `DEFERRED` — a change recorded for traceability where the underlying work has been intentionally postponed to a later milestone. The entry must name the deferring milestone in its body, and no quality-gate enforcement applies to deferred entries.

The four tag strings are uppercase ASCII only so they are unambiguous under `grep -F`. The vocabulary is closed: adding a fifth tag requires a follow-up spec and is not permitted as a drive-by change.

## Retractions

When a later release fixes a defect that was originally documented as working in an earlier `docs/changelog/` entry, the earlier entry must be edited in place with a dated forward-link to the fix entry. This preserves the chronological audit trail — no rewriting of history — while surfacing known-bad-then-fixed states to future readers of the older entry. The convention exists so that a contributor opening an older changelog entry to understand past behavior cannot be silently misled by prose that was accurate at the time but became wrong after a later fix landed.

The retraction is recorded as a new `### Retractions` sub-section appended to the original entry. The original prose body, bullet list, file references, and QA notes of the historical entry must NOT be modified — only the new `### Retractions` sub-heading and its bullets are added. Each bullet uses the exact form:

```text
- [YYYY-MM-DD] Retracted by [YYMMDD#anchor](./YYMMDD.md#anchor): <one-line reason>
```

The date in square brackets is the retraction date (the date the bullet is authored, not the date of the original entry). The link target is a GitHub-flavored-markdown anchor of the form `[YYMMDD#anchor](./YYMMDD.md#anchor)` pointing at the dated fix entry under `docs/changelog/`. Retraction bullets are NOT scope-tagged with the M11 vocabulary: the closed tags `FULL`, `LITE`, `SKELETON`, and `DEFERRED` apply only to top-level dated changelog entry headings, never to retraction bullets.

Retractions must NEVER be applied to entries that pre-date this convention commit by more than nine months, to bound the audit-and-edit obligation on contributors. The convention applies regardless of which scope tag (`FULL`, `LITE`, `SKELETON`, or `DEFERRED`) the original entry carries; even a `SKELETON` entry can be retracted if the skeleton itself was promised but never landed. The fix entry that triggers a retraction must reciprocally reference the entry it retracts via a `Retracts: [YYMMDD#anchor]` line under the fix entry's `### Notes` block (or under any equivalent metadata block the entry uses). When a fix later turns out to be incomplete, the original retraction bullet stays in place and a second retraction bullet with a new date and a new fix-entry-link is appended below the first — earlier retraction bullets are never deleted, edited, or re-dated.

### Worked example

Suppose `docs/changelog/260501.md` originally documented a working tmux-runtime feature, and a later entry `docs/changelog/260612.md` fixed a regression in that feature. Both halves of the round-trip look like this.

The modified historical entry (`docs/changelog/260501.md`) gains a `### Retractions` sub-section at the bottom; its original `### Summary`, `### Added`, `### Files`, and `### QA Notes` blocks remain byte-for-byte unchanged:

~~~markdown
## 260501 - [FULL] tmux runtime keepalive

### Summary
…original prose, unchanged…

### Files
…original list, unchanged…

### Retractions
- [2026-06-15] Retracted by [260612#tmux-keepalive-regression-fix](./260612.md#tmux-keepalive-regression-fix): keepalive ping interval regressed in CI; superseded by the fix entry.
~~~

The fix entry (`docs/changelog/260612.md`) records the reciprocal link under `### Notes`:

~~~markdown
## 260612 - [FULL] tmux keepalive regression fix

### Summary
…fix prose…

### Notes
Retracts: [260501#tmux-runtime-keepalive](./260501.md#tmux-runtime-keepalive)
~~~

If the fix later proves incomplete and a second repair lands in `docs/changelog/260801.md`, the historical entry gains a second retraction bullet without disturbing the first:

~~~markdown
### Retractions
- [2026-06-15] Retracted by [260612#tmux-keepalive-regression-fix](./260612.md#tmux-keepalive-regression-fix): keepalive ping interval regressed in CI; superseded by the fix entry.
- [2026-08-01] Retracted by [260801#tmux-keepalive-regression-fix-v2](./260801.md#tmux-keepalive-regression-fix-v2): the earlier fix re-regressed in a second environment; superseded by the second fix entry.
~~~

The example is illustrative — `260501.md`, `260612.md`, and `260801.md` are fictional in this section, and the anchor slugs follow the GitHub-flavored-markdown auto-slug rule (lowercase, spaces replaced by hyphens) for their corresponding heading text. Landing a real retraction in an actual historical entry is handled by the follow-up sub-milestone M12b.

## sw-style discipline

Most milestones in this repo ship under a `sw run` workflow whose
discipline is encoded directly in the codebase. New contributors
landing changes the manual way should still respect the same
guardrails — they are what keeps the audit-floor invariants green
and the frozen gate surface stable.

### TDD pattern

Each milestone lands as a chain of small commits in this order:

1. New behavioral test first (red).
2. Implementation second (green).
3. Audit / regression test pinning the invariant.
4. Doc / status report under `docs/audit/`.
5. Workflow archive commit (`chore(workflows): ...`).

Tests use `unittest`; invocation is always prefixed with
`PYTHONPATH=skills/bmad-story-automator/src` because the runtime
lives inside the installed skill, not at the repo root.

### Conventional Commits + Generated-By trailer

Every commit uses Conventional Commits and carries a `Generated-By:`
git trailer naming the model. Pairings + the `Co-Authored-By` line
are kept stable. The trailer is required so the audit log can map
each commit back to the agent that authored it; reviewers reject
commits without the trailer.

### Audit-floor invariants (11 green)

`tests/test_audit_regression.py` is the audit-floor regression net.
Every contribution MUST keep that suite green. "11 green" counts
invariant **classes** (the structural unit each "+1 invariant"
milestone increments); the same suite currently exposes 45 test
methods across those 11 classes, because most invariants pin
several orthogonal sub-behaviors. When milestone summaries quote
a delta (e.g. CLAUDE.md's G2 "10 → 11"), they refer to the class
count; when an older summary quotes a method-count delta (e.g.
the G7-era "24 → 26"), the prose annotates which metric it used.
The invariants are each pinned to a specific frozen-surface
behavior — see `docs/spec/frozen-gate-surface.md` for the
per-invariant mapping. One of the current 11
(`UnifiedStateWriteIsolationInvariant`, two test methods inside
that single class) was added by milestone G7 in this session;
future invariants will land the same way:

1. Add a new test method to `tests/test_audit_regression.py`.
2. Reference it in `docs/spec/frozen-gate-surface.md` under
   "Frozen behaviors" with a single-row description.
3. Verify the test fails on the pre-fix tree and passes on the
   post-fix tree before merging.

Once an invariant lands, it MUST NOT be skipped, narrowed, or
removed; regressing the class count below 11 is a release-blocking
condition.

### Sibling-module pattern (audit_env_scrub, spec_drift_persistence, gate_lock_observability)

When a module approaches the 500-LOC soft limit OR when a new
behavior is conceptually orthogonal to the parent, extract it into
a sibling module rather than growing the parent. Three examples
land this session:

- `core/audit_env_scrub.py` — extracted from `core/audit.py` so the
  D-04 trust-boundary helper has its own home; `audit.py` re-exports
  `scrub_env_for_subprocess` for the ~25 existing call sites. The
  AST audit-floor invariant skips whichever module defines the
  helper, so the split is rename-proof.
- `core/innovation/spec_drift_persistence.py` — extracted from
  `core/innovation/spec_drift_watcher.py` to host the disk-backed
  baseline + JSONL events writer; keeps the watcher under the
  500-LOC soft cap.
- `core/gate_lock_observability.py` — extracted from
  `core/gate_orchestrator.py` to host the
  `GateLockTimeoutError` raise + `_describe_lock_holder` helpers;
  cut a +145 LOC budget excursion to +88.

When extracting, keep the parent module's public surface stable
(re-export the moved symbol if it is part of the frozen surface or
has external call sites), add the sibling to the relevant module-map
section in `CLAUDE.md`, and update the frozen-surface doc.

### Additive-only `gate_file` field rule

`core/gate_schema.GateFile` is frozen. The orchestrator MAY stamp
additional top-level fields on the dict AFTER `evaluate_gate`
returns, but every such field MUST be additive: no rename, no
removal, no signature narrowing. Consumers MUST tolerate the
presence (or absence) of these fields. Currently four fields are
embedded by the orchestrator outside the schema:

- `evidence_merkle_root: str` — N5; canonical-JSON sha256 of the
  evidence bundle (or `""` when empty).
- `lineage_root: str` — C2 follow-up; sha256 of the cross-genre
  lineage Merkle chain (or `""` when no chain exists on disk).
- `cost_total_usd: float` — C3; CONDITIONAL on `session_usage`
  being supplied AND emission succeeding.
- `fail_closed_triggered: bool` + `fail_closed_categories: list[str]`
  — phase-2; CONDITIONAL on `fail_closed=True`.

Adding a fifth field requires (a) a sibling helper that emits it
best-effort (try/except around the disk write), (b) a frozen-surface
update under the relevant module section, (c) a per-field
"CONDITIONAL when…" note in the schema doc, and (d) a regression
test pinning that the field is absent on the default code path.

## Pre-commit hook (optional but recommended)

This repository ships an opt-in pre-commit gate that runs the full
`unittest` suite, `ruff check`, and the M11 changelog vocabulary gate
before every commit. It is **not** auto-installed — neither by
`npm install` nor by `install.sh`. Operators opt in once per clone:

```
./scripts/install-hooks.sh
```

This sets the project-local `core.hooksPath` to `.githooks/`. To skip
the gate for a single commit, prefer the git-native escape:

```
git commit --no-verify ...
```

For ad-hoc batches (e.g., a long rebase) the env-var escape is:

```
BMAD_SKIP_PRECOMMIT=1 git commit ...
```

To uninstall:

```
./scripts/uninstall-hooks.sh
```

The hook does not source `.envrc` or `.env`; direnv users may need to
arrange their venv activation independently. The hook autodetects
`python3` / `python` / `py` and a venv-local `ruff` if available.

## Reporting Bugs

Include:
- OS
- Python version
- Node version
- BMAD skill layout under `.claude/skills`
- exact command run
- exact error output
