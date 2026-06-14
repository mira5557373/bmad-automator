# M14 — SECURITY.md Rewrite Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rewrite the repository-root `SECURITY.md` from the legacy bmad-automator content into a current, scannable, six-section operator document that matches the M14 spec (preamble + Orchestrator posture + Trust boundary + Forbidden actions + Required environment + Supported Versions + Reporting a vulnerability), backed by a `unittest`-driven structural test.

**Architecture:** This is a documentation-only milestone with no production Python changes. We add a single test module, `tests/test_security_md.py`, that parses `SECURITY.md` from disk and asserts every spec requirement (REQ-02 through REQ-13) as a separate test method. These are document-structure assertions, not behaviour tests of the runtime — they encode the spec contract so future edits to `SECURITY.md` cannot silently regress the operator trust contract. The spec's Out-of-scope clause "no new tests of behaviour" is respected: nothing here exercises Python control flow. We then rewrite `SECURITY.md` section by section so each commit takes a small number of tests from red to green. Existing quality gates (`ruff`, `ruff format --check`, `unittest discover`, coverage) continue to apply unchanged, and a final task runs the full gate locally before commit.

**Tech Stack:** Python 3.11 `unittest`, ruff, GitHub-flavoured markdown, no third-party additions.

---

## File Structure

- Create: `tests/test_security_md.py` — single test module containing every structural assertion (one method per spec REQ). Lives next to the rest of the `unittest` suite so `python -m unittest discover -s tests -t .` picks it up automatically.
- Rewrite: `SECURITY.md` (repo root) — full replacement of the legacy 24-line file. Final document must be at or under 500 lines (REQ-13) and use level-two markdown headings only for the seven required sections (REQ-09).
- Do not touch: any file under `skills/bmad-story-automator/src/`, `tests/test_*.py` other than the new module, `CONTRIBUTING.md`, `README.md`, or `docs/changelog/`. Explicitly out of scope per the spec.

---

## Preflight (must complete before Task 1)

- [ ] **Preflight Step 1: Confirm REQ-11 target path exists in code.**

Run: `python -c "from pathlib import Path; p=Path('skills/bmad-story-automator/src/story_automator/core/common.py'); s=p.read_text(encoding='utf-8'); assert 'def iso_now' in s and 'def compact_json' in s and 'def write_atomic' in s; print('ok')"`
Expected: prints `ok`. If it fails, STOP — the spec's REQ-11 cannot be satisfied; escalate to the human operator before any further work.

- [ ] **Preflight Step 2: Confirm Claude orchestrator flag is in code.**

Run: `python -c "from pathlib import Path; s=Path('skills/bmad-story-automator/src/story_automator/core/tmux_runtime.py').read_text(encoding='utf-8'); assert '--dangerously-skip-permissions' in s; print('ok')"`
Expected: prints `ok`.

- [ ] **Preflight Step 3: Confirm Codex orchestrator flags are in code.**

Run: `python -c "from pathlib import Path; s=Path('skills/bmad-story-automator/src/story_automator/commands/tmux.py').read_text(encoding='utf-8'); assert 'workspace-write' in s and 'approval_policy' in s; print('ok')"`
Expected: prints `ok`.

- [ ] **Preflight Step 4: Note status of forward-referenced symbols.**

Run:

```
python -c "
from pathlib import Path
import subprocess

tele = Path('skills/bmad-story-automator/src/story_automator/core/telemetry_events.py')
print('REQ-10 telemetry_events.py:', 'present' if tele.exists() else 'missing')

def grep(token):
    out = subprocess.run(
        ['grep','-r','-l',token,'skills/bmad-story-automator/src/'],
        capture_output=True, text=True
    )
    return out.stdout.strip() or 'missing'

print('REQ-06 BMAD_AUDIT_KEY usage:', grep('BMAD_AUDIT_KEY'))
print('REQ-06 BMAD_ALLOW_CEILING_BYPASS usage:', grep('BMAD_ALLOW_CEILING_BYPASS'))
"
```

Expected: any of `present` or one or more source file paths is good; any line ending in `missing` is a 🔴-architectural dependency on a milestone that has not landed yet.

If anything is `missing`: REQ-10 and REQ-06 demand SECURITY.md reference these symbols by exact name even though they are not yet wired in source. The spec also states M14 depends on M04 for the audit feature docs, and M04 depends on M01 for the event surface. Proceeding under `missing` ships a doc that points at code that does not yet exist on `main`. This is acceptable only if the operator has confirmed M01/M04 are landing in the same merge train as M14; otherwise STOP and surface the dependency gap before continuing. Record the chosen path (all-present / proceed-with-forward-reference / stop) in the PR description.

- [ ] **Preflight Step 5: Confirm tooling is on PATH.**

Run: `python -c "import shutil,sys; need=['ruff','coverage']; missing=[t for t in need if not shutil.which(t)]; sys.exit(0 if not missing else (print('missing:',missing) or 1))"`
Expected: exits 0. If it prints `missing: [...]`, install the listed tools (`pip install ruff coverage`) before running Task 10. The spec quality gates name these tools by name and the plan's gates depend on them.

- [ ] **Preflight Step 6: Record baseline coverage on the runtime package.**

Run: `coverage run -m unittest discover -s tests -t . && coverage report --include='skills/bmad-story-automator/src/story_automator/*' | tail -n 1`
Expected: prints the `TOTAL` row with a coverage percentage. Record that percentage. M14 changes no source under `src/`, so the percentage measured in Task 10 Step 4 must equal this baseline. If the baseline is already below 85 percent, the spec's 85-percent gate is unmet by the project independent of M14 — surface this in the PR description so the human operator can decide whether to proceed; do not ship a SECURITY.md that claims compliance the project does not actually have.

---

## Task 1: Add structural test for SECURITY.md

**Files:**

- Create: `tests/test_security_md.py`
- Test: `tests/test_security_md.py`

- [ ] **Step 1: Write the failing test module.**

```python
from __future__ import annotations

import re
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SECURITY_MD = REPO_ROOT / "SECURITY.md"

REQUIRED_H2_HEADINGS = [
    "Orchestrator posture",
    "Trust boundary",
    "Forbidden actions",
    "Required environment",
    "Supported Versions",
    "Reporting a vulnerability",
]

# REQ-12: the spec calls out a "four-letter family that contributors use to
# mark deferred work". TODO is the canonical member; XXXX and HACK appear in
# the wider repo. The scaffold marker "filled in by Task" is local to this
# plan and must be gone at merge time.
PLACEHOLDER_MARKERS = ("TODO", "XXXX", "HACK", "filled in by Task")


def _load() -> str:
    return SECURITY_MD.read_text(encoding="utf-8")


def _lines() -> list[str]:
    return _load().splitlines()


def _h2_headings(text: str) -> list[str]:
    return [line[3:].strip() for line in text.splitlines() if line.startswith("## ")]


def _section_body(text: str, heading: str) -> str:
    lines = text.splitlines()
    start = None
    for i, line in enumerate(lines):
        if line.startswith("## ") and line[3:].strip() == heading:
            start = i + 1
            break
    if start is None:
        return ""
    end = len(lines)
    for j in range(start, len(lines)):
        if lines[j].startswith("## "):
            end = j
            break
    return "\n".join(lines[start:end])


class SecurityMdStructureTests(unittest.TestCase):
    """Structural assertions about the repository-root SECURITY.md document.

    These are document-shape checks, not behaviour tests of the Python
    runtime — they encode the M14 spec contract (REQ-02 through REQ-13 plus
    the rendering NFRs) so that future edits to SECURITY.md cannot silently
    regress the operator-facing trust contract.
    """

    def test_file_exists(self) -> None:
        self.assertTrue(SECURITY_MD.exists(), "SECURITY.md must exist at repo root")

    def test_under_500_lines(self) -> None:
        # REQ-13: file must stay under 500 lines (strict).
        self.assertLess(len(_lines()), 500)

    def test_no_placeholder_markers(self) -> None:
        # REQ-12: the spec's four-letter deferred-work family plus the
        # scaffold marker introduced in Task 2 of the plan.
        body = _load()
        for marker in PLACEHOLDER_MARKERS:
            self.assertNotIn(marker, body, f"residual placeholder marker: {marker!r}")

    def test_no_emoji(self) -> None:
        # NFR: no emoji or other non-text glyphs so downstream lint tools
        # (markdownlint, prettier) stay quiet. ASCII-only is the strictest
        # safe rule for an operator-facing security doc.
        body = _load()
        try:
            body.encode("ascii")
        except UnicodeEncodeError as exc:  # pragma: no cover - assertion path
            self.fail(f"SECURITY.md must be ASCII-only; offending char: {exc}")

    def test_no_trailing_whitespace(self) -> None:
        for i, line in enumerate(_lines(), start=1):
            self.assertEqual(
                line.rstrip(), line, f"trailing whitespace on line {i}: {line!r}"
            )

    def test_balanced_code_fences(self) -> None:
        # Quality gate: every opening ``` must have a matching closing ```.
        fences = sum(1 for line in _lines() if line.startswith("```"))
        self.assertEqual(fences % 2, 0, "unbalanced ``` code fences")

    def test_h2_headings_match_required(self) -> None:
        # REQ-09: every spec-required section is a level-two heading and
        # they are the only level-two headings in the document.
        self.assertEqual(_h2_headings(_load()), REQUIRED_H2_HEADINGS)

    def test_preamble_mentions_runtime(self) -> None:
        # REQ-02: preamble paragraph before the first ## must name the port,
        # link to CONTRIBUTING.md as a real markdown link, and state that
        # the orchestrator runs autonomously with permission prompts
        # suppressed. Word order may be "permission prompts ... suppressed"
        # or "suppresses ... permission prompts" — both are accepted.
        head = _load().split("\n## ", 1)[0]
        self.assertIn("bmad-story-automator", head)
        self.assertRegex(head, r"\]\(\.?/?CONTRIBUTING\.md\)")
        self.assertIn("permission prompt", head.lower())
        self.assertRegex(head, r"(suppress|unattended)")

    def test_acronyms_expanded_on_first_use(self) -> None:
        # NFR: any acronym (LLM, BMAD, REQ) must appear expanded on first
        # use. Pin LLM's expansion to a known phrase; BMAD and REQ are
        # covered by manual review since their canonical expansions are
        # project-internal.
        self.assertIn("Large Language Model (LLM)", _load())

    def test_orchestrator_posture_section(self) -> None:
        # REQ-03
        body = _section_body(_load(), "Orchestrator posture")
        self.assertIn("--dangerously-skip-permissions", body)
        self.assertIn("approval_policy", body)
        self.assertIn("workspace-write", body)
        self.assertIn("--full-auto", body)
        # REQ-03 also requires the doc to explain that these flags are
        # deliberate and required for unattended operation.
        self.assertIn("deliberate", body.lower())
        self.assertIn("unattended", body.lower())

    def test_trust_boundary_section(self) -> None:
        # REQ-04
        body = _section_body(_load(), "Trust boundary")
        self.assertIn("story file", body.lower())
        self.assertIn("BMAD project root", body)
        self.assertIn("agent-config-presets.json", body)
        self.assertIn("trusted", body.lower())
        self.assertRegex(body, r"not sanitis(ed|ized)")

    def test_forbidden_actions_section(self) -> None:
        # REQ-05
        body = _section_body(_load(), "Forbidden actions")
        self.assertRegex(body, r"\bcd\b")
        self.assertIn("skills/bmad-story-automator/src/", body)
        self.assertIn("sprint-status.yaml", body)
        self.assertRegex(body, r"LLM.*compliance")
        self.assertIn("not enforced by the Python runtime", body)

    def test_required_environment_section(self) -> None:
        # REQ-06
        body = _section_body(_load(), "Required environment")
        self.assertIn("BMAD_AUDIT_KEY", body)
        self.assertIn("BMAD_ALLOW_CEILING_BYPASS", body)
        self.assertIn("M04", body)
        self.assertIn("encrypt", body.lower())
        self.assertIn("unset", body)

    def test_supported_versions_table(self) -> None:
        # REQ-07: header + separator + at least two data rows; every data
        # row has exactly two cells.
        body = _section_body(_load(), "Supported Versions")
        rows = [line for line in body.splitlines() if line.startswith("|")]
        self.assertGreaterEqual(len(rows), 4, "need header + separator + 2 data rows")
        header = [c.strip() for c in rows[0].strip("|").split("|")]
        self.assertEqual(header, ["Version", "Supported"])
        sep = rows[1]
        self.assertRegex(sep, r"^\|\s*:?-+:?\s*\|\s*:?-+:?\s*\|$")
        for data_row in rows[2:]:
            cells = [c.strip() for c in data_row.strip("|").split("|")]
            self.assertEqual(len(cells), 2, f"row {data_row!r} must have 2 cells")

    def test_reporting_vulnerability_section(self) -> None:
        # REQ-08
        body = _section_body(_load(), "Reporting a vulnerability")
        self.assertRegex(body, r"@")  # contact channel
        # Numeric response window (e.g. "5 business days").
        self.assertRegex(body, re.compile(r"\d+\s*business\s*day", re.IGNORECASE))
        self.assertRegex(
            body, re.compile(r"(do not|must not).*public GitHub issue", re.IGNORECASE)
        )

    def test_telemetry_events_path_reference(self) -> None:
        # REQ-10
        self.assertIn(
            "skills/bmad-story-automator/src/story_automator/core/telemetry_events.py",
            _load(),
        )

    def test_common_py_path_reference(self) -> None:
        # REQ-11
        body = _load()
        self.assertIn(
            "skills/bmad-story-automator/src/story_automator/core/common.py", body
        )
        for helper in ("iso_now", "compact_json", "write_atomic"):
            self.assertIn(helper, body)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
```

- [ ] **Step 2: Run the new test module to verify every test fails against the legacy SECURITY.md.**

Run: `python -m unittest tests.test_security_md -v`
Expected: many failures, including `test_h2_headings_match_required`, `test_preamble_mentions_runtime`, `test_orchestrator_posture_section`, `test_supported_versions_table`, `test_telemetry_events_path_reference`, `test_common_py_path_reference`. `test_file_exists` should still pass.

- [ ] **Step 3: Confirm ruff is clean on the new test file.**

Run: `ruff check tests/test_security_md.py && ruff format --check tests/test_security_md.py`
Expected: both commands exit 0. If `ruff format --check` fails, run `ruff format tests/test_security_md.py` and re-check.

- [ ] **Step 4: Commit the failing tests.**

```bash
git add tests/test_security_md.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "test(m14): add structural test for SECURITY.md rewrite"
```

---

## Task 2: Replace SECURITY.md with seven-section scaffold

**Files:**

- Modify: `SECURITY.md` (full rewrite — overwrite the legacy 24-line content)

- [ ] **Step 1: Replace `SECURITY.md` with a scaffold that has the preamble plus all six level-two headings, ASCII-only and trailing-whitespace-free.**

```markdown
# Security Policy

The bmad-story-automator port runs a Claude- and Codex-driven orchestration loop that
spawns short-lived child agent sessions inside `tmux`. The orchestrator runs unattended
and deliberately suppresses interactive permission prompts. See
[`CONTRIBUTING.md`](./CONTRIBUTING.md) for contributor guidance, and read this document
in full before invoking the skill in any project you do not own.

## Orchestrator posture

Section body filled in by Task 3.

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
```

- [ ] **Step 2: Verify heading-level tests now pass.**

Run: `python -m unittest tests.test_security_md.SecurityMdStructureTests.test_h2_headings_match_required tests.test_security_md.SecurityMdStructureTests.test_preamble_mentions_runtime tests.test_security_md.SecurityMdStructureTests.test_balanced_code_fences tests.test_security_md.SecurityMdStructureTests.test_no_trailing_whitespace tests.test_security_md.SecurityMdStructureTests.test_no_emoji -v`
Expected: all five pass.

- [ ] **Step 3: Verify the body-content tests still fail (they depend on the per-section tasks below).**

Run: `python -m unittest tests.test_security_md -v`
Expected: `test_orchestrator_posture_section`, `test_trust_boundary_section`, `test_forbidden_actions_section`, `test_required_environment_section`, `test_supported_versions_table`, `test_reporting_vulnerability_section`, `test_telemetry_events_path_reference`, `test_common_py_path_reference`, `test_acronyms_expanded_on_first_use`, and `test_no_placeholder_markers` (because the scaffold still contains "filled in by Task") all fail at this stage. The first five tests from Step 2 must still pass.

- [ ] **Step 4: Commit the scaffold.**

```bash
git add SECURITY.md
git commit --trailer "Generated-By: claude-opus-4-7" -m "docs(m14): scaffold SECURITY.md with seven required sections"
```

---

## Task 3: Write the Orchestrator posture section (REQ-03)

**Files:**

- Modify: `SECURITY.md` — replace the `Orchestrator posture` placeholder body.

- [ ] **Step 1: Replace the placeholder body under `## Orchestrator posture` with the following content.**

```markdown
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
```

- [ ] **Step 2: Verify the posture test passes.**

Run: `python -m unittest tests.test_security_md.SecurityMdStructureTests.test_orchestrator_posture_section -v`
Expected: PASS.

- [ ] **Step 3: Commit.**

```bash
git add SECURITY.md
git commit --trailer "Generated-By: claude-opus-4-7" -m "docs(m14): write Orchestrator posture section"
```

---

## Task 4: Write the Trust boundary section (REQ-04)

**Files:**

- Modify: `SECURITY.md` — replace the `Trust boundary` placeholder body.

- [ ] **Step 1: Replace the placeholder body under `## Trust boundary` with the following content.**

```markdown
## Trust boundary

The orchestrator reads three inputs and treats them as trusted. They are not
sanitised, escaped, or sandboxed before being passed to a child agent or interpolated
into a prompt.

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
```

- [ ] **Step 2: Verify the trust boundary test passes.**

Run: `python -m unittest tests.test_security_md.SecurityMdStructureTests.test_trust_boundary_section -v`
Expected: PASS.

- [ ] **Step 3: Commit.**

```bash
git add SECURITY.md
git commit --trailer "Generated-By: claude-opus-4-7" -m "docs(m14): write Trust boundary section"
```

---

## Task 5: Write the Forbidden actions section (REQ-05)

**Files:**

- Modify: `SECURITY.md` — replace the `Forbidden actions` placeholder body.

- [ ] **Step 1: Replace the placeholder body under `## Forbidden actions` with the following content.**

```markdown
## Forbidden actions

The orchestrator instructs the Large Language Model (LLM) agent to refuse three
classes of action while it runs. These prohibitions are LLM-compliance contracts.
They are encoded in the prompt and the skill instructions. They are not enforced by
the Python runtime, by the operating-system sandbox, or by any pre-commit hook. A
sufficiently confused or adversarial agent could violate any of them.

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
```

- [ ] **Step 2: Verify the forbidden actions test passes.**

Run: `python -m unittest tests.test_security_md.SecurityMdStructureTests.test_forbidden_actions_section -v`
Expected: PASS.

- [ ] **Step 3: Commit.**

```bash
git add SECURITY.md
git commit --trailer "Generated-By: claude-opus-4-7" -m "docs(m14): write Forbidden actions section"
```

---

## Task 6: Write the Required environment section (REQ-06, REQ-10, REQ-11)

**Files:**

- Modify: `SECURITY.md` — replace the `Required environment` placeholder body.

- [ ] **Step 1: Replace the placeholder body under `## Required environment` with the following content.**

```markdown
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
```

- [ ] **Step 2: Verify the environment, REQ-10 path, and REQ-11 path tests pass.**

Run: `python -m unittest tests.test_security_md.SecurityMdStructureTests.test_required_environment_section tests.test_security_md.SecurityMdStructureTests.test_telemetry_events_path_reference tests.test_security_md.SecurityMdStructureTests.test_common_py_path_reference -v`
Expected: all three PASS.

- [ ] **Step 3: Commit.**

```bash
git add SECURITY.md
git commit --trailer "Generated-By: claude-opus-4-7" -m "docs(m14): write Required environment section"
```

---

## Task 7: Write the Supported Versions table (REQ-07)

**Files:**

- Modify: `SECURITY.md` — replace the `Supported Versions` placeholder body.

- [ ] **Step 1: Determine the current and prior minor release lines from `package.json`.**

Run: `python -c "import json; v=json.load(open('package.json'))['version']; major,minor,_=v.split('.'); print(f'{major}.{minor}',f'{major}.{int(minor)-1}')"`
Expected: prints two version strings on one line, e.g. `1.15 1.14`. Use the first as the current minor line and the second as the prior minor line.

- [ ] **Step 2: Replace the placeholder body under `## Supported Versions` with the following content, substituting the two minor lines from Step 1 into the table.**

```markdown
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
```

If the Step 1 command printed a different pair, edit the `Version` column accordingly before saving. The `1.15.x` / `1.14.x` rows above match the version pinned in `package.json` at the time this plan was written.

- [ ] **Step 3: Verify the versions table test passes.**

Run: `python -m unittest tests.test_security_md.SecurityMdStructureTests.test_supported_versions_table -v`
Expected: PASS.

- [ ] **Step 4: Commit.**

```bash
git add SECURITY.md
git commit --trailer "Generated-By: claude-opus-4-7" -m "docs(m14): add Supported Versions table"
```

---

## Task 8: Write the Reporting a vulnerability section (REQ-08)

**Files:**

- Modify: `SECURITY.md` — replace the `Reporting a vulnerability` placeholder body.

- [ ] **Step 1: Replace the placeholder body under `## Reporting a vulnerability` with the following content.**

```markdown
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
```

- [ ] **Step 2: Verify the reporting test passes.**

Run: `python -m unittest tests.test_security_md.SecurityMdStructureTests.test_reporting_vulnerability_section -v`
Expected: PASS.

- [ ] **Step 3: Commit.**

```bash
git add SECURITY.md
git commit --trailer "Generated-By: claude-opus-4-7" -m "docs(m14): write Reporting a vulnerability section"
```

---

## Task 9: Final structural pass and placeholder sweep (REQ-12, REQ-13)

**Files:**

- Modify: `SECURITY.md` — only if the sweep finds residual placeholder text or trailing whitespace.

- [ ] **Step 1: Run the full structural test module.**

Run: `python -m unittest tests.test_security_md -v`
Expected: every test passes. If any fail, fix the offending section in `SECURITY.md` (no shortcuts: do not loosen the test).

- [ ] **Step 2: Manually grep for residual placeholder language that the automated test does not catch.**

Run: `grep -nE '\b(TODO|TBD|XXXX|FIXME|filled in by Task)\b' SECURITY.md || echo 'clean'`
Expected: prints `clean`. If anything else prints, fix the file and rerun.

- [ ] **Step 3: Confirm line count.**

Run: `python -c "from pathlib import Path; print(len(Path('SECURITY.md').read_text(encoding='utf-8').splitlines()))"`
Expected: prints an integer at or below `500`. If above, tighten prose; do not split sections.

- [ ] **Step 4: Commit only if Steps 1-3 required any edits; otherwise skip.**

```bash
git add SECURITY.md
git commit --trailer "Generated-By: claude-opus-4-7" -m "docs(m14): final structural sweep on SECURITY.md"
```

---

## Task 10: Run the full quality gate suite

**Files:** none modified.

- [ ] **Step 1: Run `ruff check` over the Python module and the tests.**

Run: `ruff check skills/bmad-story-automator/src/story_automator tests`
Expected: no findings (exit 0).

- [ ] **Step 2: Run `ruff format --check` over the same set.**

Run: `ruff format --check skills/bmad-story-automator/src/story_automator tests`
Expected: no formatting drift (exit 0). If it fails, run `ruff format tests/test_security_md.py` (the only file M14 added) and re-check.

- [ ] **Step 3: Run the full unittest suite.**

Run: `python -m unittest discover -s tests -t .`
Expected: 0 failures, 0 errors. The new `test_security_md` cases are picked up automatically by discovery.

- [ ] **Step 4: Confirm coverage on the runtime package is still at or above 85 percent.**

Run: `coverage run -m unittest discover -s tests -t . && coverage report --include='skills/bmad-story-automator/src/story_automator/*'`
Expected: the bottom-line `TOTAL` row shows a coverage percentage at or above `85%`. Because M14 adds no Python source under `src/`, the only way this can drop is if the suite shrank — which it did not.

- [ ] **Step 5: Confirm the new test file did not pull in a forbidden third-party import.**

Run: `python -c "import ast,sys; t=ast.parse(open('tests/test_security_md.py').read()); mods=set(); [mods.update([n.name.split('.')[0]] if isinstance(node,ast.Import) else [node.module.split('.')[0]] if isinstance(node,ast.ImportFrom) and node.module else []) for node in ast.walk(t)]; allowed={'__future__','re','unittest','pathlib'}; bad=mods-allowed; sys.exit(0 if not bad else (print('forbidden imports:',bad) or 1))"`
Expected: exits 0. If it fails, remove the offending import from `tests/test_security_md.py`.

- [ ] **Step 6: Confirm every Python module under the runtime package is still at or under 500 lines.**

Run: `python -c "from pathlib import Path; bad=[p for p in Path('skills/bmad-story-automator/src/story_automator').rglob('*.py') if sum(1 for _ in p.open(encoding='utf-8'))>500]; print('clean' if not bad else bad)"`
Expected: prints `clean`. M14 should not be moving this gate, but the suite is cheap.

- [ ] **Step 7: Final commit only if a previous step required an edit. Otherwise, no-op.**

If `ruff format` adjusted `tests/test_security_md.py`:

```bash
git add tests/test_security_md.py
git commit --trailer "Generated-By: claude-opus-4-7" -m "style(m14): ruff format test_security_md"
```

---

## Self-Review checklist (run before handing off)

- REQ-01 (full rewrite of `SECURITY.md`) → Task 2 overwrites the file and Tasks 3-8 fill the body.
- REQ-02 (preamble) → Task 2 Step 1 + `test_preamble_mentions_runtime`.
- REQ-03 (Orchestrator posture) → Task 3 + `test_orchestrator_posture_section`.
- REQ-04 (Trust boundary) → Task 4 + `test_trust_boundary_section`.
- REQ-05 (Forbidden actions) → Task 5 + `test_forbidden_actions_section`.
- REQ-06 (Required environment) → Task 6 + `test_required_environment_section`.
- REQ-07 (Supported Versions) → Task 7 + `test_supported_versions_table`.
- REQ-08 (Reporting a vulnerability) → Task 8 + `test_reporting_vulnerability_section`.
- REQ-09 (all required sections at `##`) → `test_h2_headings_match_required` in Task 1.
- REQ-10 (telemetry_events.py path) → Task 6 + `test_telemetry_events_path_reference`. Preflight Step 4 surfaces the M01 dependency.
- REQ-11 (common.py path + helpers) → Task 6 + `test_common_py_path_reference`.
- REQ-12 (no four-letter deferred-work marker) → `test_no_placeholder_markers` plus the Task 9 Step 2 wider grep.
- REQ-13 (under 500 lines) → `test_under_500_lines` plus the Task 9 Step 3 explicit check.
- NFR acronym expansion (LLM/BMAD/REQ) → `test_acronyms_expanded_on_first_use` pins LLM; BMAD/REQ verified by manual review of the rewritten document.
- Quality gates (ruff, ruff format, unittest, coverage, import allowlist, 500-line module rule, balanced fences, valid table) → Task 10 plus the dedicated tests added in Task 1; coverage baseline captured in Preflight Step 6 so M14 cannot be blamed for a pre-existing coverage gap.
