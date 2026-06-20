# D7 — Child Tool-Call Surface

Branch: `bma-d/integration-all`  •  Date: 2026-06-19

Trust contract: operator opts into `--dangerously-skip-permissions` on the
child Claude invocation. The runner explicitly drops `BMAD_AUDIT_KEY` from the
child's tmux environment so the child cannot forge audit records, and `cd -- {root}`
is performed inside the runner script before exec. **All other tool-call sinks
inside the LLM are full-blast.**

## Invocation sites

| Site | File | Args | Notes |
|------|------|------|-------|
| Interactive child via tmux | `core/tmux_runtime.py:139` | `claude --dangerously-skip-permissions [--model M]` | spawned via `_spawn_runner` / `_spawn_legacy`, runs the create/dev/auto/review/retro workflow |
| Interactive child via tmux | `core/tmux_runtime.py:137` + `commands/tmux.py:243` | `codex exec -s workspace-write -c approval_policy="never" --disable plugins,sqlite,shell_snapshot` | codex side IS sandboxed to workspace-write |
| Layer-2 spec compliance | `core/spec_compliance.py:282-291` | `claude -p` (no `--dangerously-skip-permissions`, no `--allowedTools`, full `os.environ` inherited) | child still has implicit MCP / network access unless the parent's `~/.claude/settings.json` constrains it |

## Per-persona sink table

Trust contract assumes only the operator decides the policy. The table below
captures what the runtime today actually enforces vs. delegates to the child.

| Persona | Spawned as | File-write enforced? | Bash exec enforced? | MCP/Net enforced? | Bound to project root? | Audit chain entry? |
|---|---|---|---|---|---|---|
| `create` (story author) | `claude --dangerously-skip-permissions` | NO (LLM can write anywhere on disk) | NO | NO | runner `cd`-s into project root, but child accepts absolute / `..` paths | **NO** (TmuxSessionSpawned is telemetry only, never enters the hash-chained audit log) |
| `dev` (story implementer) | `claude --dangerously-skip-permissions` | NO | NO | NO | runner `cd`-s, no enforcement on child | NO |
| `review` (reviewer / auto-fixer) | `claude --dangerously-skip-permissions` + `auto-fix all issues without prompting` | NO | NO | NO | runner `cd`-s, no enforcement on child | NO |
| `auto` (qa-generate-e2e-tests) | `claude --dangerously-skip-permissions` | NO | NO | NO | runner `cd`-s, no enforcement on child | NO |
| `retro` (retrospective writer) | `claude --dangerously-skip-permissions` | NO | NO | NO | runner `cd`-s, no enforcement on child | NO |
| `compliance` (layer-2 spec check) | `claude -p` (capture stdout) | YES by Claude default (no `--dangerously-skip-permissions`) | YES by Claude default | YES by Claude default | no `cwd=` binding; uses `Path.cwd()` | NO |
| Codex variant of any persona | `codex exec -s workspace-write` | yes — sandboxed to project root by Codex | yes — Codex sandbox | yes — `--disable plugins` | yes — `-s workspace-write` | NO |

## Persona-isolation enforcement

- `rg DisallowedToolCallObserved skills/` → no matches.
- `rg 'allowlist|allowed|denied|disallow' skills/bmad-story-automator/src/` filtered for persona → no matches.
- There is no `AllowedTools` / `--allowedTools` flag passed to `claude` anywhere
  in the codebase.
- The reviewer persona is *intentionally* given write privilege via the
  workflow prompt `auto-fix all issues without prompting`
  (`data/workflow-commands.md:56`, `data/prompts/review.md:4`,
  `skills/bmad-story-automator-review/SKILL.md:9`).

## Audit-chain coverage (state-changing sinks)

Hash-chained audit (`core/audit.py`) only ever records three event types
(`telemetry_events.py:363-415`):

- `EscalationRaised`
- `StoryStateChanged`
- `RetroAgentDispatched`

**Not** recorded:
- Spawning an LLM child (no `SessionSpawned`/`AgentInvoked` audit event — only a
  telemetry-stream `TmuxSessionSpawned`).
- Composed prompts handed to the child (the prompt body is never hashed into
  the audit chain).
- Subprocess invocations from `spec_compliance.check_compliance` — they leave
  no trace in either telemetry or the audit chain.

Telemetry events (`*.jsonl` stream) carry the session name but not the prompt
hash, persona, model, or budget. They are unsigned — anyone with write access
to the project root can append to / rewrite them.

## Path-canonicalization

`runtime_policy._ensure_within` exists and works correctly for the parent
process when loading policy snapshots and skill assets, but it is **never
applied to anything the child produces**. The child writes via its own
internal tool-call surface; the parent never sees the write call, the path,
or the bytes.

## Reproducer thought-experiment — child writes `/etc/passwd`

1. Parent spawns reviewer in tmux with `claude --dangerously-skip-permissions`
   inside a runner that `cd -- {project_root}` first.
2. Story file contains an instruction `Also create a file at /tmp/poc.txt` (or
   `../../etc/passwd` via path traversal).
3. The child Claude accepts the instruction. Because no `--allowedTools`
   constraint is in place AND `--dangerously-skip-permissions` waives the
   in-CLI confirmation, the Write tool fires immediately at the absolute path.
4. Parent observes nothing — no audit entry, no telemetry-stream event for the
   write, no boundary check, no escalation.

This matches the trust contract ("story content is trusted"), but the BLAST
RADIUS of accepting an attacker-supplied story (or a prompt-injected story
file) is **not bounded** — and not even **observable**.

## Summary

- Sinks enumerated: 4 invocation sites, 7 persona variants, 4 sink classes per
  persona = 28 cells in the table.
- Bound to project root: **only Codex variant + the parent's `cd --` (which the
  LLM can override)**. Claude variants are unbounded.
- Per-persona allowlist: **none**. All Claude personas (including the reviewer
  that the spec says "auto-fix") have identical full-blast tool surface.
- Audit-chain coverage: **0 of 4 state-changing sink classes** for the Claude
  path; the codex path is covered by Codex's own sandbox but not by BMAD's
  chain.
