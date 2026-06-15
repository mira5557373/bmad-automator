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


_DECISION_VALUES = {"pass", "warn", "block"}
_OUTPUT_REQUIRED_KEYS = {"layer1", "layer2", "layer3", "decision", "verified_at"}
_LAYER1_KEYS = {"statuses", "overall_confidence", "validated_at"}
_LAYER2_KEYS = {"verdicts", "spec_path", "diff_sha", "model_invocation_ms"}
_LAYER3_ENTRY_KEYS = {
    "req_id",
    "existing_test_path",
    "created_test_path",
    "action",
}
_LAYER3_ACTIONS = {"found", "created", "skipped"}


class OutputFixtureShapeTests(unittest.TestCase):
    """REQ-13 + REQ-05: sample output fixture matches the chain emit shape."""

    def setUp(self) -> None:
        self.data = json.loads(OUTPUT_FIXTURE.read_text(encoding="utf-8"))

    def test_top_level_has_exactly_required_keys(self) -> None:
        self.assertEqual(set(self.data), _OUTPUT_REQUIRED_KEYS)

    def test_decision_is_allowed_literal(self) -> None:
        self.assertIn(self.data["decision"], _DECISION_VALUES)

    def test_verified_at_is_iso8601_z_string(self) -> None:
        verified_at = self.data["verified_at"]
        self.assertIsInstance(verified_at, str)
        self.assertRegex(
            verified_at,
            r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?Z$",
        )

    def test_layer1_has_validation_report_keys(self) -> None:
        layer1 = self.data["layer1"]
        self.assertIsInstance(layer1, dict)
        self.assertEqual(set(layer1), _LAYER1_KEYS)
        self.assertIsInstance(layer1["statuses"], list)
        self.assertIsInstance(layer1["overall_confidence"], (int, float))
        self.assertGreaterEqual(layer1["overall_confidence"], 0.0)
        self.assertLessEqual(layer1["overall_confidence"], 1.0)

    def test_layer2_has_compliance_report_keys(self) -> None:
        layer2 = self.data["layer2"]
        self.assertIsInstance(layer2, dict)
        self.assertEqual(set(layer2), _LAYER2_KEYS)
        self.assertIsInstance(layer2["verdicts"], list)
        self.assertFalse(isinstance(layer2["model_invocation_ms"], bool))
        self.assertIsInstance(layer2["model_invocation_ms"], int)
        self.assertGreaterEqual(layer2["model_invocation_ms"], 0)

    def test_layer3_is_list_of_plan_entries(self) -> None:
        layer3 = self.data["layer3"]
        self.assertIsInstance(layer3, list)
        for index, entry in enumerate(layer3):
            self.assertIsInstance(entry, dict, msg=f"layer3[{index}] not object")
            self.assertEqual(
                set(entry), _LAYER3_ENTRY_KEYS, msg=f"layer3[{index}] key set"
            )
            self.assertIn(
                entry["action"], _LAYER3_ACTIONS, msg=f"layer3[{index}].action"
            )


class SkillMdReq01Tests(unittest.TestCase):
    """REQ-01: SKILL bundle at skills/trust-but-verify/ with single SKILL.md
    that names the three M06a modules and declares L1 -> L2 -> L3 order."""

    def setUp(self) -> None:
        self.text = _require_markdown(self, SKILL_MD)

    def test_skill_dir_contains_only_skill_md(self) -> None:
        names = sorted(
            p.name for p in SKILL_DIR.iterdir() if not p.name.startswith(".")
        )
        self.assertEqual(
            names,
            ["SKILL.md"],
            msg=f"skills/trust-but-verify/ must contain only SKILL.md, got {names}",
        )

    def test_skill_md_names_all_three_layer_module_paths(self) -> None:
        for module_path in (
            "core/gap_validator.py",
            "core/spec_compliance.py",
            "core/feature_tester.py",
        ):
            self.assertIn(
                module_path,
                self.text,
                msg=f"SKILL.md must name layer module path {module_path!r}",
            )

    def test_skill_md_declares_invocation_order(self) -> None:
        l1 = self.text.find("Layer 1")
        l2 = self.text.find("Layer 2")
        l3 = self.text.find("Layer 3")
        self.assertNotEqual(l1, -1, msg="SKILL.md missing 'Layer 1' marker")
        self.assertGreater(l2, l1, msg="'Layer 2' must appear after 'Layer 1'")
        self.assertGreater(l3, l2, msg="'Layer 3' must appear after 'Layer 2'")


class SkillMdReq02Tests(unittest.TestCase):
    """REQ-02: ## Trigger section names the four documented triggers."""

    def setUp(self) -> None:
        self.text = _require_markdown(self, SKILL_MD)

    def test_trigger_section_present(self) -> None:
        self.assertRegex(
            self.text,
            r"(?m)^## Trigger\s*$",
            msg="SKILL.md must include a level-2 '## Trigger' heading",
        )

    def test_all_four_triggers_named(self) -> None:
        needles = (
            "/sw-trust-verify",
            "step-03a",
            "Dev Story",
            "orchestrator menu",
        )
        missing = [n for n in needles if n not in self.text]
        self.assertEqual(
            missing,
            [],
            msg=f"SKILL.md ## Trigger section missing references: {missing}",
        )


class SkillMdReq03Tests(unittest.TestCase):
    """REQ-03: ## Pre-conditions section names the four documented prereqs."""

    def setUp(self) -> None:
        self.text = _require_markdown(self, SKILL_MD)

    def test_preconditions_section_present(self) -> None:
        self.assertRegex(
            self.text,
            r"(?m)^## Pre-conditions\s*$",
            msg="SKILL.md must include a level-2 '## Pre-conditions' heading",
        )

    def test_all_four_preconditions_named(self) -> None:
        needles = (
            "story file",
            ".claude/trust-verify-input/gaps.json",
            "spec",
            "git working tree",
        )
        missing = [n for n in needles if n not in self.text]
        self.assertEqual(
            missing,
            [],
            msg=f"SKILL.md ## Pre-conditions missing references: {missing}",
        )


if __name__ == "__main__":
    unittest.main()
