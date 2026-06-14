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

The orchestrator instructs the Large Language Model (LLM) agent to refuse three
classes of action while it runs. These prohibitions are LLM-compliance contracts.
They are encoded in the prompt and the skill instructions. They are
not enforced by the Python runtime, by the operating-system sandbox, or by any
pre-commit hook. A sufficiently confused or adversarial agent could violate any
of them.

1. No `cd` into other directories. The agent must operate from the BMAD project
   root supplied on the command line and must not change directory into sibling
   projects, parent directories, or the user's home.
2. No edits to source files under `skills/bmad-story-automator/src/`. The
   orchestrator's own Python runtime is off-limits to the agent it spawns; the
   agent works on stories, not on the automator itself.
3. No writes to `sprint-status.yaml`. That file is the sprint's source of truth and
   is maintained by the BMAD review and retrospective workflows, not by the dev
   agent.

If you observe an agent breaking any of these contracts, treat it as a security
event and report it through the disclosure path below.

## Required environment

Two environment variables shape the security-relevant behaviour of the orchestrator.

`BMAD_AUDIT_KEY` opts the operator into the M04 audit log. When set to a non-empty
value, the orchestrator emits structured audit events to a file in the project's
state directory, encrypted under the key. The full event surface is defined in
`skills/bmad-story-automator/src/story_automator/core/telemetry_events.py` so the
operator can audit the schema directly. The audit writer uses the helpers
`iso_now`, `compact_json`, and `write_atomic` from
`skills/bmad-story-automator/src/story_automator/core/common.py`, so timestamps,
serialisation, and on-disk format are consistent across event types. If
`BMAD_AUDIT_KEY` is unset, no audit file is written; the operator gives up the
audit trail in exchange for zero key-management overhead.

`BMAD_ALLOW_CEILING_BYPASS` must remain unset in normal operation. It exists only
so that maintainers can run integration tests against retry-ceiling behaviour
without tripping the production guard. Setting it in a real run silently disables a
safety check and is not a supported configuration.

## Supported Versions

Only the current minor release line and the immediately preceding minor release line
receive security fixes. Older lines are not patched; operators on those lines must
upgrade before reporting an issue.

| Version | Supported          |
| ------- | ------------------ |
| 1.15.x  | Yes                |
| 1.14.x  | Yes                |
| < 1.14  | No                 |

The minor lines listed above track `package.json` at the head of `main`. Patch
releases inside a supported minor line are always considered supported.

## Reporting a vulnerability

Do not open a public GitHub issue for a credential leak, an agent that breaks one of
the forbidden-actions contracts, or any other security-sensitive problem. Public
issues are indexed and cached the moment they are filed, and we cannot pull a leaked
secret out of search results after the fact.

Send a private report to `bmad.directory@gmail.com` instead. Include:

- the affected version (npm `bmad-story-automator` version or the exact commit hash)
- reproduction steps that work on a clean checkout
- the impact you observed (data exposure, agent escape, command injection, etc.)
- whether the issue affects install-time behaviour, the generated command wrappers,
  or runtime orchestration

You should receive an acknowledgement within 5 business days. We will coordinate a fix
and disclosure timeline privately before any public write-up.
