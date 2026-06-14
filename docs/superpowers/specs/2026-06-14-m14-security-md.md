# M14 — security-md

## Context

The bmad-automator port runs orchestration logic on behalf of a human operator who has explicitly opted into an autonomous coding loop. The orchestrator spawns child agents (Claude Code with `--dangerously-skip-permissions`, Codex with `approval_policy=never` + `workspace-write` + `--full-auto`) and reads story files, config presets, and BMAD project state. Because the runtime intentionally suppresses interactive permission prompts, the human operator needs a clear, current SECURITY.md that describes the trust boundary, what the orchestrator is allowed to touch, what it must never touch, and how to opt into the audit trail introduced in M04. The current `SECURITY.md` predates the Story Automator port and references the legacy bmad-automator surface; it does not describe the new dangerous-skip-permissions posture, the audit key, the ceiling-bypass env var, or the orchestrator forbidden-action contract. M14 rewrites `SECURITY.md` at the repository root so that operators reading it before first run understand exactly what they are authorizing, what could go wrong, and where to report a vulnerability. This is a documentation-only milestone with no Python source changes; it depends on M04 because the audit feature docs must already exist before SECURITY.md can reference them by name.

## Out of scope

M14 does not modify any Python source under `skills/bmad-story-automator/src/story_automator/`. The telemetry event types defined in M01 at `skills/bmad-story-automator/src/story_automator/core/telemetry_events.py`, the M02 log-site wiring in `skills/bmad-story-automator/src/story_automator/commands/orchestrator.py` and `skills/bmad-story-automator/src/story_automator/commands/orchestrator_epic_agents.py`, the M03 tmux runtime in `skills/bmad-story-automator/src/story_automator/core/tmux_runtime.py`, the M04 audit-log writer, the M05 frontmatter parser that replaces the regex in `skills/bmad-story-automator/src/story_automator/commands/state.py`, the M06-M10 command refactors, and the M12-M13 packaging changes are all owned by other milestones and are not touched here. M14 also does not modify `CONTRIBUTING.md` (M11's responsibility) or backfill changelog entries under `docs/changelog/YYMMDD.md` (also M11). No new dependencies, no new tests of behaviour, and no schema changes are introduced — M14 is strictly a rewrite of the top-level `SECURITY.md` markdown file plus addition of a Supported Versions matrix and a disclosure path. Threat-modelling of the BMAD upstream submodule under `external/BMAD-METHOD` is also out of scope; SECURITY.md only describes the bmad-automator port's own surface.

## Functional requirements

1. REQ-01 The repository root file `SECURITY.md` must be rewritten in full to replace the legacy bmad-automator content with the four sections enumerated in REQ-03 through REQ-06.
2. REQ-02 `SECURITY.md` must open with a one-paragraph preamble that names the bmad-automator port, links to `CONTRIBUTING.md` for contributor guidance, and states that the orchestrator runs autonomously with permission prompts suppressed.
3. REQ-03 `SECURITY.md` must contain a top-level section titled "Orchestrator posture" that documents the Claude Code invocation flag `--dangerously-skip-permissions` and the Codex invocation flags `approval_policy=never`, `sandbox=workspace-write`, and `--full-auto`, and must explain that these flags are deliberate and required for unattended operation.
4. REQ-04 `SECURITY.md` must contain a top-level section titled "Trust boundary" that enumerates the three trusted inputs the orchestrator reads: story file content under the BMAD project's stories directory, the BMAD project root path supplied on the command line, and `agent-config-presets.json`, and must state that these inputs are treated as trusted and not sanitised.
5. REQ-05 `SECURITY.md` must contain a top-level section titled "Forbidden actions" that lists the three orchestrator forbidden actions: no `cd` into other directories, no edits to source files under `skills/bmad-story-automator/src/`, and no writes to `sprint-status.yaml`, and must state explicitly that these prohibitions are LLM-compliance contracts and are not enforced by the Python runtime.
6. REQ-06 `SECURITY.md` must contain a top-level section titled "Required environment" that documents `BMAD_AUDIT_KEY` as the opt-in audit log encryption key (referencing the M04 audit feature) and documents that `BMAD_ALLOW_CEILING_BYPASS` must remain unset in normal operation.
7. REQ-07 `SECURITY.md` must contain a top-level section titled "Supported Versions" that renders a markdown table with columns `Version` and `Supported` covering at minimum the current minor release line and the immediately preceding minor release line.
8. REQ-08 `SECURITY.md` must contain a top-level section titled "Reporting a vulnerability" that documents the disclosure path, including the contact channel, expected response window, and a statement that public GitHub issues must not be used for security reports.
9. REQ-09 Every section heading required by REQ-02 through REQ-08 must use a level-two markdown heading (`##`) so that the document renders with a flat, scannable table of contents on GitHub.
10. REQ-10 The rewritten `SECURITY.md` must reference `skills/bmad-story-automator/src/story_automator/core/telemetry_events.py` by exact path when describing what events are emitted under the audit-key opt-in, so readers can audit the event surface directly.
11. REQ-11 The rewritten `SECURITY.md` must reference `skills/bmad-story-automator/src/story_automator/core/common.py` by exact path when describing the helpers (`iso_now`, `compact_json`, `write_atomic`) used by the audit writer.
12. REQ-12 The rewritten `SECURITY.md` must not contain unresolved placeholder tokens (the four-letter family that contributors use to mark deferred work); every claim must be concrete and final at merge time.
13. REQ-13 The rewritten `SECURITY.md` must remain under 500 lines so that it stays scannable in a single GitHub page view without virtual scrolling.

## Non-functional requirements

- The rewritten `SECURITY.md` must render correctly on GitHub's markdown renderer with no broken code-fence pairs, no malformed tables, and no relative links that resolve outside the repository.
- The document must be reviewable in under ten minutes by a security-conscious operator who has never seen the bmad-automator port before; sections must be ordered from posture to boundary to forbidden actions to environment to versions to disclosure so that the reader builds a mental model in that order.
- The document must use plain US English and avoid jargon that is not defined in-line; any acronym (LLM, BMAD, REQ) must appear expanded on first use.
- The document must avoid emoji, decorative ASCII art, and trailing whitespace so that downstream lint tools (markdownlint, prettier) do not flag it.

## Quality gates

- `ruff check skills/bmad-story-automator/src/story_automator tests` passes with no findings (no Python changed, gate must still be green).
- `ruff format --check skills/bmad-story-automator/src/story_automator tests` passes with no formatting drift.
- `python -m unittest discover -s tests -t .` passes with no failures or errors.
- Coverage on `skills/bmad-story-automator/src/story_automator/` remains at or above 85 percent line coverage when measured with `coverage run -m unittest discover` followed by `coverage report`.
- Import allowlist for any touched Python module (none expected in M14) remains restricted to the Python 3.11 standard library plus `filelock` and `psutil`; no other third-party imports may be introduced.
- Every Python module under `skills/bmad-story-automator/src/story_automator/` remains at or below 500 lines of source; the rewritten `SECURITY.md` itself remains at or below 500 lines per REQ-13.
- `SECURITY.md` contains no unresolved placeholder tokens of the four-letter-deferred family when grepped at the repository root.
- All markdown code fences in `SECURITY.md` are balanced (every opening ``` has a matching closing ```).
- The Supported Versions section parses as a valid GitHub-flavoured markdown table with a header row, a separator row, and at least two data rows.
