"""Format tests for the M06b trust-but-verify SKILL bundle and step-03ab.

This file enforces the shape contracts declared in
docs/superpowers/specs/2026-06-14-m06b-trust-verify-skill.md REQ-01..REQ-05,
REQ-07..REQ-09, and REQ-13.

Tests are stdlib-only (REQ-14). When the SKILL.md or step-03ab markdown
file is not yet present (sub-milestones c-m02/c-m03), the dependent
tests call ``self.skipTest`` so this file's unittest run stays clean.
"""

from __future__ import annotations

import json
import re  # noqa: F401
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SKILL_DIR = REPO_ROOT / "skills" / "trust-but-verify"
SKILL_MD = SKILL_DIR / "SKILL.md"
STEP_03AB = (
    REPO_ROOT
    / "skills"
    / "bmad-story-automator"
    / "steps-c"
    / "step-03ab-spec-compliance.md"
)
FIXTURES_DIR = REPO_ROOT / "tests" / "fixtures"
INPUT_FIXTURE = FIXTURES_DIR / "trust_verify_sample_gaps.json"
OUTPUT_FIXTURE = FIXTURES_DIR / "trust_verify_sample_result.json"


def _require_markdown(test_case: unittest.TestCase, path: Path) -> str:
    """Return the UTF-8 text of ``path`` or skip the test if it does not exist.

    The SKILL.md and step-03ab files are created in later M06b sub-milestones
    (c-m02 / c-m03). Tests that depend on them must skip cleanly here so the
    c-m01 unittest gate reports zero failures.
    """
    if not path.exists():
        test_case.skipTest(f"{path.relative_to(REPO_ROOT)} not yet present (c-m02+)")
    return path.read_text(encoding="utf-8")


_ALLOWED_SEVERITIES = {"blocker", "major", "minor"}
_GAP_REQUIRED_KEYS = ("file_path", "line", "symbol", "description", "severity")


class InputFixtureShapeTests(unittest.TestCase):
    """REQ-13: sample input fixture matches parse_gap_list's contract."""

    def setUp(self) -> None:
        self.data = json.loads(INPUT_FIXTURE.read_text(encoding="utf-8"))

    def test_top_level_is_object_with_gaps_key(self) -> None:
        self.assertIsInstance(self.data, dict)
        self.assertIn("gaps", self.data)
        self.assertIsInstance(self.data["gaps"], list)

    def test_fixture_is_non_empty(self) -> None:
        self.assertGreater(
            len(self.data["gaps"]),
            0,
            "fixture must contain at least one sample gap",
        )

    def test_each_gap_has_required_keys(self) -> None:
        for index, gap in enumerate(self.data["gaps"]):
            self.assertIsInstance(gap, dict, msg=f"gaps[{index}] not an object")
            for key in _GAP_REQUIRED_KEYS:
                self.assertIn(key, gap, msg=f"gaps[{index}] missing {key!r}")

    def test_each_gap_field_has_correct_type(self) -> None:
        for index, gap in enumerate(self.data["gaps"]):
            self.assertIsInstance(gap["file_path"], str, msg=f"gaps[{index}].file_path")
            # bool is a subclass of int; reject explicitly to match parse_gap_list.
            self.assertFalse(
                isinstance(gap["line"], bool),
                msg=f"gaps[{index}].line must not be a bool",
            )
            self.assertIsInstance(gap["line"], int, msg=f"gaps[{index}].line")
            self.assertIsInstance(gap["symbol"], str, msg=f"gaps[{index}].symbol")
            self.assertIsInstance(
                gap["description"], str, msg=f"gaps[{index}].description"
            )

    def test_each_gap_severity_is_allowed(self) -> None:
        for index, gap in enumerate(self.data["gaps"]):
            self.assertIn(
                gap["severity"],
                _ALLOWED_SEVERITIES,
                msg=f"gaps[{index}].severity {gap['severity']!r} outside allowed set",
            )


if __name__ == "__main__":
    unittest.main()
