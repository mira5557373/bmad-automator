# Phases 4-6 Deferral — bmad-auto Pattern Adoption

**Status:** deferred  
**Author:** autonomous adoption run (2026-06-21)  
**Predecessors:** [Phase 0](./frozen-gate-surface.md) (audit-floor), Phase 1 (`phase-1-defensive-primitives`), Phase 2 (`phase-2-result-schema-and-policy`), Phase 3 (`phase-3-pre-gate-verifier`)  
**Next sync:** after operator review of Phases 1-3 in production use

This document captures **why** Phases 4-6 of the bmad-auto pattern adoption were deferred during the autonomous run, the open questions they each block on, and the smallest defensible additive starts that *could* land now if any of them become time-sensitive. The intent is to leave a clean handoff: anyone resuming work should be able to pick up each phase without re-reading the entire conversation log.

## TL;DR

| Phase | Scope | Why deferred | Defensible additive starter |
| --- | --- | --- | --- |
| 4 | TUI watcher + optional Textual extras group | Adds a runtime dep that conflicts with the "stdlib + filelock + psutil" hard guardrail; needs operator approval for an extras group | A `core/run_view.py` stdlib-only descriptor (`build_run_overview()`) that any future TUI can render |
| 5 | CLIProfile dataclass + stop_hooks dispatch | Multi-CLI orchestration changes the trust-boundary story; needs a spec waiver discussion for Codex/Gemini commit-signing | A `core/cli_profile.py` frozen dataclass (no dispatch) so the schema is fixed even before adapters land |
| 6 | Action enum + plugin settings overlay | Pairs with 5; defining a plugin overlay before 5's CLI dispatch lands creates schema drift | A `core/action_enum.py` Literal type + ``ACTION_NAMES`` tuple so call sites can start narrowing strings to the enum |

The recommendation is to **ship Phases 0-3 to one real story first**, gather operator signal, and then choose whether 4-6 are worth the additional surface. If something is time-critical, the "defensible additive starter" column gives a 100-LOC change that does not block on any open question.

## Phase 4 — TUI watcher + Textual extras group

### What bmad-auto provides

bmad-auto ships a Textual TUI (`automator/tui/`) that:
- Tail-renders the run journal as it advances
- Lets the operator scroll past completed work without losing the live tail
- Surfaces escalations and waivers inline with the task tree
- Provides keyboard shortcuts to pause/resume the orchestrator

### Why we deferred

1. **Dependency policy.** The hard guardrail in `CLAUDE.md` forbids new Python deps beyond stdlib + filelock + psutil. Textual is a substantial runtime dep with its own transitive tree (rich, markdown-it-py, mdurl, pygments). Importing Textual unconditionally violates the guardrail; making it an extras group requires:
   - Editing `pyproject.toml` to declare `[project.optional-dependencies] tui = ["textual>=...,<..."]`
   - Updating `package.json` so `bin/bmad-story-automator` does not import TUI code at import time
   - Bumping CI to run a parallel "tui" matrix that installs the extras and exercises the watcher
   - Auditing the cross-platform smoke test path (`scripts/smoke-test.sh`) to confirm the extras install does not break Windows git-bash or WSL Ubuntu
2. **No operator demand yet.** The orchestrator currently runs to completion in one shot; the TUI's biggest win is operator situational awareness during long runs. Until we have a single user reporting that they cannot follow what is happening, the carrying cost is not justified.
3. **Plugin authoring complexity.** Textual widgets in Python are stateful by design (mount/unmount lifecycle) and do not compose well with the deterministic state machine that the rest of the runtime uses. Adopting Textual draws a new boundary inside the package that future maintainers must understand.

### Open questions blocking adoption

- **Q4.1** Where do the Textual extras live in our hybrid npm/pip package shape? `pyproject.toml` is read by pip but `package.json` is the npm bin entry. The extras group needs to be invokable from both install paths.
- **Q4.2** What does the watcher render when the operator is over SSH on a tty that does not support 256-color? bmad-auto assumes a modern terminal; we ship to whatever the operator has.
- **Q4.3** Should the TUI be a separate skill (`skills/bmad-story-automator-watch/`) so installing it is opt-in at the marketplace level rather than a pip extras invocation? The marketplace metaphor matches our distribution model better than pip extras do.

### Defensible additive starter (≤150 LOC, no deferred questions)

`core/run_view.py` — a stdlib-only module that builds a deterministic snapshot of the current run:

```python
def build_run_overview(project_root: Path) -> dict:
    """Return a dict describing the current run for display.

    No timestamps, no PIDs — just the same data a TUI would render:
    {workflow_state, current_step, parked_stories, mitigation_debt,
     last_gate_verdict, last_audit_event}.
    """
```

This lets a future TUI (or a simple `--watch` CLI flag using ANSI cursor moves) render the same data without committing to Textual. The starter does not block on any of Q4.1–Q4.3.

## Phase 5 — CLIProfile dataclass + stop_hooks dispatch

### What bmad-auto provides

bmad-auto supports more than one upstream LLM CLI (Claude Code, Codex, Gemini) via a `CLIProfile` dataclass that captures:
- The binary path
- The system-prompt injection point
- The stop-hook command (how the orchestrator detects "the session is done")
- The commit-signing posture (auto-sign vs require GPG vs reject)

The orchestrator's session dispatcher chooses a profile per task, runs the session, and parses its exit signal via the registered stop-hook.

### Why we deferred

1. **Trust boundary change.** Our current trust-boundary contract assumes Claude Code as the sole upstream and validates the host context accordingly (`core/trust_boundary.py`). Adding Codex/Gemini means deciding whether their stop-hooks are allowed inside the same trust boundary or whether each CLI gets its own host-context check. That is a spec-level conversation, not a code-level decision.
2. **Commit signing divergence.** Claude Code does not commit on the operator's behalf today; Codex sometimes does and Gemini's behavior is in flux. The orchestrator's "Generated-By trailer" convention assumes Claude — we need a story for how a Codex-driven commit advertises its origin without lying about the upstream model.
3. **Stop-hook timing risk.** The stop-hook is the contract: "the session is done when this command exits 0." If we ship the dispatcher with stop-hook plumbing that races against the journal writer, we could ship a worse "did it actually commit?" detector than what Phase 1's `lie_detector` already gives us. That race needs a deliberate fix before multi-CLI is safe.

### Open questions blocking adoption

- **Q5.1** Does the Codex stop-hook signal completion before its commit lands on disk? bmad-auto's verifier handles the race; we have not exercised it.
- **Q5.2** Should the `Generated-By` trailer name a CLI brand (`claude-code`, `codex`, `gemini-cli`) in addition to a model? If yes, that breaks every existing commit-search query (`git log --grep "Generated-By: claude"`); if no, we are misattributing.
- **Q5.3** What is the policy when an operator says "use Codex for the dev step and Claude for the code-review step in the same story"? Per-task profile selection makes the policy file's schema more complex; per-session profile selection keeps it simple but forfeits the optimization.

### Defensible additive starter (≤80 LOC, no deferred questions)

`core/cli_profile.py` — a frozen dataclass schema with no dispatch logic:

```python
@dataclass(frozen=True)
class CLIProfile:
    cli_id: str            # "claude-code" | "codex" | "gemini-cli"
    model_id: str          # full model ID, e.g. "claude-opus-4-7"
    binary_path: str       # absolute or PATH-resolved
    stop_hook: str         # shell command; exits 0 when session done
    trailer_label: str     # for Generated-By: <trailer_label>
```

Plus a constants tuple `KNOWN_CLI_IDS = ("claude-code",)` initially. This freezes the schema so anyone porting bmad-auto's dispatcher later does not have to redesign it from scratch, but does not engage any of Q5.1–Q5.3.

## Phase 6 — Action enum + plugin settings overlay

### What bmad-auto provides

bmad-auto's policy machinery uses a string-typed action union (`"defer"`, `"escalate"`, `"retry"`, `"commit"`, `"park"`, etc.) and a plugin settings overlay file (`policy.local.toml`) that lets operators tweak hook behavior without forking the upstream policy.

### Why we deferred

1. **Pairs with Phase 5.** The action enum is most useful when the orchestrator has to choose between multi-CLI behaviors that produce different action sets. Defining the enum before 5's CLIProfile lands risks adding actions we then remove.
2. **Overlay format spike risk.** TOML or JSON for the overlay? bmad-auto picked TOML because the operator audience already runs `pyproject.toml`; our operator audience runs through the marketplace and may not have a TOML mental model. The format choice is a community-norm decision, not a technical one.
3. **Schema versioning of the overlay.** Adding an overlay file introduces a third schema (alongside `data/profiles/*.json` and the new `result.json`). Each schema bump must be coordinated; we are not ready to pay that complexity tax yet.

### Open questions blocking adoption

- **Q6.1** Should the overlay live under `_bmad/` (operator-private) or under `.claude-plugin/` (marketplace-visible)? The choice signals whether overlays are personal customization or distributable presets.
- **Q6.2** What is the API_VERSION discipline across overlay/result/profile/gate schemas — one shared version or independent versions? The single-version choice simplifies upgrades; the independent choice means a result.json bump does not force a profile re-render.
- **Q6.3** Do plugin authors get to *add* actions, or only configure the dispatch table for the actions we ship? Adding actions is a much larger sandboxing concern.

### Defensible additive starter (≤60 LOC, no deferred questions)

`core/action_enum.py` — a Literal type and a tuple:

```python
from typing import Literal

ACTION_NAMES = ("done", "remediate", "park", "baseline_drift",
                "pre_gate_failed")
Action = Literal["done", "remediate", "park", "baseline_drift",
                 "pre_gate_failed"]
```

This narrows the existing string-typed action fields the orchestrator already returns (`route_gate_verdict` returns `"done"`/`"remediate"`/`"park"`; `run_production_gate` Phase 1/3 added `"baseline_drift"`/`"pre_gate_failed"`). Anyone consuming the orchestrator output gets a type-checkable contract. The starter does not engage any of Q6.1–Q6.3.

## Recommended sequence after operator review

1. Run Phases 0-3 on at least one real production story (a non-toy artifact through the full gate).
2. Capture the operator's pain points after the run (TUI gap? multi-CLI need? overlay request?).
3. Score each of Phases 4-6 against the captured pain points; promote the highest-scoring one to "next milestone" status.
4. Land the matching defensible additive starter from this doc as the entry-point commit for that milestone.
5. Open a spec PR to resolve the open questions for the selected phase before adding the runtime behavior.

## Cross-reference

| Artifact | Path |
| --- | --- |
| Frozen surface contract | `docs/spec/frozen-gate-surface.md` |
| Audit-regression suite (Phase 0) | `tests/test_audit_regression.py` |
| Phase 1 commit tag | `phase-1-defensive-primitives` |
| Phase 2 commit tag | `phase-2-result-schema-and-policy` |
| Phase 3 commit tag | `phase-3-pre-gate-verifier` |
| bmad-auto submodule (reference) | `external/bmad-auto/` |
