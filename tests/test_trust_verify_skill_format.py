"""Format tests for the M06b trust-but-verify SKILL bundle and step-03ab.

This file enforces the shape contracts declared in
docs/superpowers/specs/2026-06-14-m06b-trust-verify-skill.md REQ-01..REQ-05,
REQ-07..REQ-09, and REQ-13.

Tests are stdlib-only (REQ-14). When the SKILL.md or step-03ab markdown
file is not yet present (sub-milestones c-m02/c-m03), the dependent
tests call ``self.skipTest`` so this file's unittest run stays clean.
"""

from __future__ import annotations

import json  # noqa: F401
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


if __name__ == "__main__":
    unittest.main()
