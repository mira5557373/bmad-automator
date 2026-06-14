# Security Policy

The bmad-story-automator port runs a Claude- and Codex-driven orchestration loop that
spawns short-lived child agent sessions inside `tmux`. The orchestrator runs unattended
and deliberately suppresses interactive permission prompts. See
[`CONTRIBUTING.md`](./CONTRIBUTING.md) for contributor guidance, and read this document
in full before invoking the skill in any project you do not own.

## Orchestrator posture

The orchestrator launches child agent sessions with interactive permission prompts
deliberately suppressed, because unattended operation is the entire point of this
skill. The flags below are not a bug to be patched away; they are part of the trust
contract the operator opts into when they run `bmad-story-automator`.

- Claude child sessions are launched with `claude --dangerously-skip-permissions`.
  No per-tool confirmation prompts are shown; the agent edits files, runs shell
  commands, and writes to the working tree without further human approval.
- Codex child sessions are launched with `approval_policy=never`,
  `sandbox=workspace-write`, and `--full-auto`. The Codex agent is allowed to write
  inside the workspace and is never asked to approve a tool call.

Operators who are not comfortable with this posture should not run the skill on a
machine or project they care about. There is no flag to re-enable the prompts; that
would defeat the orchestrator.

## Trust boundary

Section body filled in by Task 4.

## Forbidden actions

Section body filled in by Task 5.

## Required environment

Section body filled in by Task 6.

## Supported Versions

Section body filled in by Task 7.

## Reporting a vulnerability

Section body filled in by Task 8.
