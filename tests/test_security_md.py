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
    runtime - they encode the M14 spec contract (REQ-02 through REQ-13 plus
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
        # or "suppresses ... permission prompts" - both are accepted.
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
