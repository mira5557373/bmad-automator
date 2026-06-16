# Changelog tag audit trail (M11)

This document records the rationale for the scope tag (`FULL`, `LITE`, `SKELETON`, or `DEFERRED`) assigned to every dated entry that existed when M11 — the closed four-tag vocabulary — was introduced. The vocabulary itself is defined in `CONTRIBUTING.md`. The M11 spec is `docs/superpowers/specs/2026-06-14-m11-changelog-vocabulary.md`. The M11 implementation plans are at `docs/superpowers/plans/2026-06-14-docs-m1-vocabulary-definition.md` (vocabulary + tag insertion) and `docs/superpowers/plans/2026-06-14-docs-m2-retroactive-audit.md` (audit lock-in and verification harness).

## Methodology

Every dated entry across `docs/changelog/260401.md` through `docs/changelog/260519.md` was inspected directly. The chosen tag reflects the scope evidenced by the entry's own `### Summary`, `### Added`, `### Changed`, `### Fixed`, `### Files`, and `### QA Notes` blocks — not by git history or by the reviewer's recall. The four tags are defined in `CONTRIBUTING.md`. The vocabulary is closed; no fifth tag is permitted inside M11. A future contributor who believes a tag is wrong should open a follow-up PR that updates only the heading line of the affected entry (REQ-09, REQ-10) and updates the corresponding row in this document.

## Per-entry rationale

| # | File | Line | Heading (after tagging) | Tag | Rationale |
|---|------|------|-------------------------|-----|-----------|
| 1 | `docs/changelog/260401.md` | 3 | `## 260412 - [LITE] Pure Skill Install Layout` | `LITE` | Installer + runtime + smoke-test changes shipped together; no QA-Notes block records test runs, so depth is reduced. |
| 2 | `docs/changelog/260401.md` | 26 | `## 260401-22:47:02 - [LITE] Prepare repository for open source release` | `LITE` | Repo-wiring entry (MIT, CI, smoke harness, contributor docs); QA Notes literally `N/A`. |
| 3 | `docs/changelog/260401.md` | 61 | `## 260414-10:30:57 - [FULL] Harden tmux runtime for non-default shells` | `FULL` | New module plus dedicated tests; QA Notes run `compileall` and `unittest test_tmux_runtime`. |
| 4 | `docs/changelog/260401.md` | 85 | `## 260414-12:07:46 - [FULL] Fix Claude runner sessions that stay open at the prompt after command completion` | `FULL` | Targeted fix plus regression test updates; QA Notes run `unittest test_tmux_runtime` and `compileall`. |
| 5 | `docs/changelog/260412.md` | 3 | `## 260412-02:41:53 - [LITE] Migrate story automator installer to pure skill layout` | `LITE` | Large installer/runtime migration with bundled smoke updates; QA Notes `N/A`. |
| 6 | `docs/changelog/260412.md` | 34 | `## 260412-04:50:44 - [LITE] Close review gaps in skill migration` | `LITE` | Follow-up review-gap fixes + smoke; QA Notes `N/A`. |
| 7 | `docs/changelog/260413.md` | 3 | `## 260413-09:14:32 - [FULL] Restore verify-step retry contract` | `FULL` | Fix + unit + smoke; QA Notes run `unittest test_success_verifiers` and `smoke-test.sh`. |
| 8 | `docs/changelog/260413.md` | 27 | `## 260413-08:05:51 - [LITE] Wire policy-backed success verifiers` | `LITE` | New registry shipped with unit coverage but QA Notes `N/A`. |
| 9 | `docs/changelog/260413.md` | 51 | `## 260413-09:26:29 - [LITE] Tighten state policy compatibility helpers` | `LITE` | Compatibility fixes with tests; QA Notes `N/A`. |
| 10 | `docs/changelog/260413.md` | 77 | `## 260413-08:39:42 - [FULL] Route create validation through shared verifier` | `FULL` | Helper added, smoke + tests updated; QA Notes run `npm run verify`. |
| 11 | `docs/changelog/260413.md` | 104 | `## 260413-08:34:25 - [FULL] Harden success verifier review fixes` | `FULL` | Fix + tests + smoke; QA Notes run `npm run verify`. |
| 12 | `docs/changelog/260413.md` | 129 | `## 260413-11:35:00 - [FULL] Verify packed npx install path` | `FULL` | Release-prep entry that re-pinned the publish smoke path; QA Notes run `npm run verify`. |
| 13 | `docs/changelog/260413.md` | 148 | `## 260413-03:41:50 - [LITE] Stabilize Codex tmux review sessions` | `LITE` | Fix + smoke contract updates; QA Notes `N/A`. |
| 14 | `docs/changelog/260413.md` | 168 | `## 260413-05:03:47 - [LITE] Add comprehensive automator documentation` | `LITE` | Docs-only rewrite; no test impact and no QA Notes block. |
| 15 | `docs/changelog/260413.md` | 195 | `## 260413-06:34:01 - [SKELETON] Add JSON settings implementation plan` | `SKELETON` | Planning packet — directory tree of plan docs with no behavioral wiring, no tests. |
| 16 | `docs/changelog/260413.md` | 215 | `## 260413-07:29:16 - [LITE] Add JSON runtime policy foundation` | `LITE` | Large impl + bundled data + tests, but QA Notes `N/A`. |
| 17 | `docs/changelog/260413.md` | 250 | `## 260413-07:55:28 - [LITE] Harden runtime policy snapshot handling` | `LITE` | Snapshot/marker fixes + regression coverage; QA Notes `N/A`. |
| 18 | `docs/changelog/260413.md` | 277 | `## 260413-09:13:20 - [LITE] Enforce snapshot-only resume semantics` | `LITE` | Fixes + tests + operator docs; QA Notes `N/A`. |
| 19 | `docs/changelog/260413.md` | 302 | `## 260413-11:00:47 - [LITE] Harden parser runtime and validator compatibility` | `LITE` | Parser/validator hardening + tests; QA Notes `N/A`. |
| 20 | `docs/changelog/260413.md` | 330 | `## 260413-21:53:12 - [LITE] Close state-summary and validator compatibility gaps` | `LITE` | Compatibility-gap fixes + regression coverage; QA Notes `N/A`. |
| 21 | `docs/changelog/260414.md` | 3 | `## 260414-21:51:35 - [LITE] Harden snapshot and verifier review fixes` | `LITE` | Review-loop hardening + tests + docs; QA Notes `N/A`. |
| 22 | `docs/changelog/260415.md` | 3 | `## 260415-01:20:16 - [LITE] Harden policy resume and review parsing` | `LITE` | Snapshot/parser fixes + regression coverage; QA Notes `N/A`. |
| 23 | `docs/changelog/260415.md` | 33 | `## 260415-06:47:15 - [LITE] Harden tmux prompt and monitor contract failures` | `LITE` | Fail-closed fixes + regression coverage; QA Notes `N/A`. |
| 24 | `docs/changelog/260415.md` | 51 | `## 260415-07:54:52 - [LITE] Tighten tmux monitor output verification` | `LITE` | Fixes + regressions for verifier outcome; QA Notes `N/A`. |
| 25 | `docs/changelog/260506.md` | 3 | `## 260506-19:21:58 - [LITE] Support SKILL-only BMAD dependency installs` | `LITE` | Install + runtime relaxation + tests + docs; QA Notes `N/A`. |
| 26 | `docs/changelog/260508.md` | 3 | `## 260508-07:58:11 - [LITE] Align Claude plugin marketplace metadata` | `LITE` | Metadata + docs polish; QA Notes `N/A`. |
| 27 | `docs/changelog/260508.md` | 25 | `## 260508-01:22:06 - [LITE] Publish refreshed npx installer` | `LITE` | Pure version-bump release entry; QA Notes `N/A`. |
| 28 | `docs/changelog/260508.md` | 43 | `## 260508-01:17:06 - [LITE] Repackage automator as self-contained skills` | `LITE` | Large repackage + docs + tests update; QA Notes `N/A`. |
| 29 | `docs/changelog/260517.md` | 3 | `## 260517 - [FULL] Release Codex Runtime Support` | `FULL` | Release milestone with multi-root installer + tests + version bumps; QA Notes run `npm run verify`. |
| 30 | `docs/changelog/260519.md` | 3 | `## 260519 - [FULL] Per-Task Model Selection` | `FULL` | Large impl + 26 new tests + 4 review passes; QA Notes run 229-test discover and smoke. |

## Distribution

8 `FULL`, 20 `LITE`, 1 `SKELETON`, 0 `DEFERRED`. `DEFERRED` is reserved for future entries; the closed-vocabulary gate explicitly permits a subset of the four tags to appear.
