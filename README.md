I'm stopping before writing anything, because two things look off and I'd rather check than guess.

**1. The current `README.md` is suspicious.** It is a single line:

> "Updated README.md with overview (project goal + milestone table showing M01 done / M02 current), quickstart (test/lint/coverage/verify commands), architecture (module map + dependency allowlist + cross-platform notes), and contributing (style, commit conventions, milestone discipline, recent M02 commits)."

That reads like an assistant *summary* of a prior update, not README content. Either a previous turn wrote the summary into the file by mistake, or this is a prompt-injection-shaped payload trying to seed instructions for me. I'm flagging it rather than treating it as "existing sections to keep."

**2. The task framing conflicts with project guardrails.** `CLAUDE.md` says the active milestone is **M01** and pins the branch as `bma-d/sw-port-foundation`, but the actual working branch is `bma-d/m08-calibration` with recent `feat(m08)` / `fix(m08)` commits. The "context" pasted into your prompt is a truncated copy of CLAUDE.md, not necessarily current truth. I don't want to bake stale milestone claims ("M01 done / M02 current") into a README.

Before I write, can you confirm:
- Do you want me to **overwrite** the current one-line README with a fresh one (treating that line as junk)?
- Should the README reflect **M08 (calibration)** as the current milestone (matching the branch + commits), or **M01** (matching the pasted CLAUDE.md)?
- The directive "output only the README.md content, nothing else" — do you want me to **write the file** and stay silent, or **just print** the content to chat without touching the file?