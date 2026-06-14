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

The orchestrator reads three inputs and treats them as trusted. They are
not sanitised, escaped, or sandboxed before being passed to a child agent or
interpolated into a prompt.

1. Story file content under the BMAD project's stories directory. The orchestrator
   reads each story markdown file verbatim, including any inline shell snippets or
   prompts the author embedded.
2. The BMAD project root path supplied on the command line. The orchestrator joins
   paths against this root without rechecking that they stay inside it.
3. `agent-config-presets.json` from the installed skill directory. Each preset can
   set the child command and prompt template that the orchestrator runs.

If an attacker can influence any of these three inputs, they can influence what the
child agent does. Operators are responsible for keeping these inputs trustworthy:
do not run the orchestrator against story files, project roots, or agent-config
preset files you did not write or vet yourself.

## Forbidden actions

Section body filled in by Task 5.

## Required environment

Section body filled in by Task 6.

## Supported Versions

Section body filled in by Task 7.

## Reporting a vulnerability

Section body filled in by Task 8.
