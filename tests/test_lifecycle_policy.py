from __future__ import annotations

import unittest
from pathlib import Path

FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures" / "lifecycle"


class LifecyclePolicyModuleTests(unittest.TestCase):
    def test_module_imports(self) -> None:
        from story_automator.core import lifecycle_policy  # noqa: F401

    def test_exposes_policy_error(self) -> None:
        from story_automator.core.lifecycle_policy import PolicyError

        self.assertTrue(issubclass(PolicyError, ValueError))

    def test_exposes_load_policy(self) -> None:
        from story_automator.core.lifecycle_policy import load_policy

        self.assertTrue(callable(load_policy))


class LoadPolicyHappyPathTests(unittest.TestCase):
    def setUp(self) -> None:
        from story_automator.core.lifecycle_policy import load_policy

        self.load_policy = load_policy
        self.json_text = (FIXTURE_DIR / "greenfield-minimal.policy.json").read_text(
            encoding="utf-8"
        )

    def test_returns_policy_with_expected_node_ids(self) -> None:
        policy = self.load_policy(self.json_text)
        self.assertEqual(
            sorted(policy.nodes.keys()),
            ["B1-brief", "B2-prd", "B3-arch", "B3-epics"],
        )

    def test_node_fields_round_trip_from_fixture(self) -> None:
        policy = self.load_policy(self.json_text)
        b2 = policy.nodes["B2-prd"]
        self.assertEqual(b2.track, "bmm")
        self.assertEqual(b2.phase, 2)
        self.assertEqual(b2.skill, "bmad-create-prd")
        self.assertEqual(b2.validator_skill, "bmad-validate-prd")
        self.assertEqual(b2.deps, ["B1-brief"])
        self.assertEqual(b2.input_artifacts, ["docs/product-brief.md"])
        self.assertEqual(b2.output_artifact, "docs/prd.md")
        self.assertEqual(b2.verifier, "prd_valid")
        self.assertEqual(b2.gate, "human")
        self.assertEqual(b2.modes, ["greenfield"])
        self.assertEqual(b2.agent_role, "pm")
        self.assertTrue(b2.interactive)

    def test_optional_validator_skill_defaults_to_none(self) -> None:
        policy = self.load_policy(self.json_text)
        self.assertIsNone(policy.nodes["B1-brief"].validator_skill)

    def test_entry_map_populated(self) -> None:
        policy = self.load_policy(self.json_text)
        self.assertEqual(policy.entry.greenfield, ["B1-brief"])
        self.assertEqual(policy.entry.brownfield, [])

    def test_version_captured(self) -> None:
        policy = self.load_policy(self.json_text)
        self.assertEqual(policy.version, 1)
