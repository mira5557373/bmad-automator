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


class PolicyEnumValidationTests(unittest.TestCase):
    def setUp(self) -> None:
        from story_automator.core.lifecycle_policy import PolicyError, load_policy

        self.PolicyError = PolicyError
        self.load_policy = load_policy

    def test_invalid_gate_value_raises(self) -> None:
        text = (FIXTURE_DIR / "invalid-bad-enum.policy.json").read_text(encoding="utf-8")
        with self.assertRaises(self.PolicyError) as ctx:
            self.load_policy(text)
        self.assertIn("gate", str(ctx.exception))
        self.assertIn("B1-brief", str(ctx.exception))

    def test_invalid_mode_value_raises(self) -> None:
        import json as _json

        text = (FIXTURE_DIR / "greenfield-minimal.policy.json").read_text(encoding="utf-8")
        raw = _json.loads(text)
        raw["nodes"]["B1-brief"]["modes"] = ["greenfeld"]
        with self.assertRaises(self.PolicyError) as ctx:
            self.load_policy(_json.dumps(raw))
        self.assertIn("modes", str(ctx.exception))

    def test_empty_modes_list_raises(self) -> None:
        import json as _json

        text = (FIXTURE_DIR / "greenfield-minimal.policy.json").read_text(encoding="utf-8")
        raw = _json.loads(text)
        raw["nodes"]["B1-brief"]["modes"] = []
        with self.assertRaises(self.PolicyError) as ctx:
            self.load_policy(_json.dumps(raw))
        self.assertIn("modes", str(ctx.exception))

    def test_missing_required_field_raises(self) -> None:
        import json as _json

        text = (FIXTURE_DIR / "greenfield-minimal.policy.json").read_text(encoding="utf-8")
        raw = _json.loads(text)
        del raw["nodes"]["B2-prd"]["skill"]
        with self.assertRaises(self.PolicyError) as ctx:
            self.load_policy(_json.dumps(raw))
        self.assertIn("skill", str(ctx.exception))

    def test_non_int_phase_raises(self) -> None:
        import json as _json

        text = (FIXTURE_DIR / "greenfield-minimal.policy.json").read_text(encoding="utf-8")
        raw = _json.loads(text)
        raw["nodes"]["B2-prd"]["phase"] = "two"
        with self.assertRaises(self.PolicyError) as ctx:
            self.load_policy(_json.dumps(raw))
        self.assertIn("phase", str(ctx.exception))

    def test_invalid_json_input_raises_policy_error(self) -> None:
        with self.assertRaises(self.PolicyError) as ctx:
            self.load_policy("{not: valid, json}")
        self.assertIn("JSON", str(ctx.exception))

    def test_top_level_non_object_raises(self) -> None:
        with self.assertRaises(self.PolicyError) as ctx:
            self.load_policy("[]")
        self.assertIn("object", str(ctx.exception))


class PolicyClosedWorldTests(unittest.TestCase):
    def setUp(self) -> None:
        from story_automator.core.lifecycle_policy import PolicyError, load_policy

        self.PolicyError = PolicyError
        self.load_policy = load_policy

    def test_dep_referencing_unknown_node_raises(self) -> None:
        text = (FIXTURE_DIR / "invalid-missing-dep.policy.json").read_text(encoding="utf-8")
        with self.assertRaises(self.PolicyError) as ctx:
            self.load_policy(text)
        msg = str(ctx.exception)
        self.assertIn("B1-brief", msg)
        self.assertIn("B0-ghost", msg)

    def test_entry_referencing_unknown_node_raises(self) -> None:
        text = (FIXTURE_DIR / "invalid-entry-ref.policy.json").read_text(encoding="utf-8")
        with self.assertRaises(self.PolicyError) as ctx:
            self.load_policy(text)
        msg = str(ctx.exception)
        self.assertIn("entry", msg)
        self.assertIn("ZZ-not-a-node", msg)

    def test_self_dep_raises(self) -> None:
        import json as _json

        text = (FIXTURE_DIR / "greenfield-minimal.policy.json").read_text(encoding="utf-8")
        raw = _json.loads(text)
        raw["nodes"]["B2-prd"]["deps"] = ["B2-prd"]
        with self.assertRaises(self.PolicyError) as ctx:
            self.load_policy(_json.dumps(raw))
        self.assertIn("B2-prd", str(ctx.exception))


class PolicyCycleDetectionTests(unittest.TestCase):
    def setUp(self) -> None:
        from story_automator.core.lifecycle_policy import PolicyError, load_policy

        self.PolicyError = PolicyError
        self.load_policy = load_policy

    def test_two_node_cycle_detected(self) -> None:
        text = (FIXTURE_DIR / "invalid-cycle.policy.json").read_text(encoding="utf-8")
        with self.assertRaises(self.PolicyError) as ctx:
            self.load_policy(text)
        msg = str(ctx.exception).lower()
        self.assertIn("cycle", msg)

    def test_three_node_cycle_detected(self) -> None:
        import json as _json

        text = (FIXTURE_DIR / "greenfield-minimal.policy.json").read_text(encoding="utf-8")
        raw = _json.loads(text)
        raw["nodes"]["B1-brief"]["deps"] = ["B3-epics"]
        with self.assertRaises(self.PolicyError) as ctx:
            self.load_policy(_json.dumps(raw))
        self.assertIn("cycle", str(ctx.exception).lower())

    def test_dag_with_diamond_passes(self) -> None:
        import json as _json

        policy = {
            "version": 1,
            "nodes": {
                name: {
                    "track": "bmm",
                    "phase": 1,
                    "skill": "bmad-noop",
                    "validator_skill": None,
                    "deps": deps,
                    "input_artifacts": [],
                    "output_artifact": f"docs/{name}.md",
                    "verifier": "structural",
                    "gate": "auto",
                    "modes": ["greenfield"],
                    "agent_role": "analyst",
                    "interactive": False,
                }
                for name, deps in [
                    ("B1", []),
                    ("B2", ["B1"]),
                    ("B3", ["B1"]),
                    ("B4", ["B2", "B3"]),
                ]
            },
            "entry": {"greenfield": ["B1"], "brownfield": []},
        }
        self.load_policy(_json.dumps(policy))


class PolicyHardeningTests(unittest.TestCase):
    """Coverage for the Phase-C review gaps: bool-as-int rejection,
    unknown-field rejection, version-range, duplicate-dep guard, and entry-
    mode mismatch guard. All are operator-error edges that previously
    accepted silently or surfaced as the wrong error type."""

    def setUp(self) -> None:
        from story_automator.core.lifecycle_policy import PolicyError, load_policy

        self.PolicyError = PolicyError
        self.load_policy = load_policy
        self.base_text = (FIXTURE_DIR / "greenfield-minimal.policy.json").read_text(
            encoding="utf-8"
        )

    def test_phase_bool_rejected_despite_int_subclass(self) -> None:
        import json as _json

        raw = _json.loads(self.base_text)
        raw["nodes"]["B2-prd"]["phase"] = True
        with self.assertRaises(self.PolicyError) as ctx:
            self.load_policy(_json.dumps(raw))
        msg = str(ctx.exception)
        self.assertIn("phase", msg)
        self.assertIn("bool", msg)

    def test_version_bool_rejected(self) -> None:
        import json as _json

        raw = _json.loads(self.base_text)
        raw["version"] = True
        with self.assertRaises(self.PolicyError) as ctx:
            self.load_policy(_json.dumps(raw))
        self.assertIn("version", str(ctx.exception))

    def test_version_zero_or_negative_rejected(self) -> None:
        import json as _json

        raw = _json.loads(self.base_text)
        raw["version"] = 0
        with self.assertRaises(self.PolicyError) as ctx:
            self.load_policy(_json.dumps(raw))
        self.assertIn("version", str(ctx.exception))
        raw["version"] = -1
        with self.assertRaises(self.PolicyError):
            self.load_policy(_json.dumps(raw))

    def test_unknown_node_field_rejected(self) -> None:
        import json as _json

        raw = _json.loads(self.base_text)
        raw["nodes"]["B1-brief"]["gat"] = "human"  # typo of 'gate'
        with self.assertRaises(self.PolicyError) as ctx:
            self.load_policy(_json.dumps(raw))
        msg = str(ctx.exception)
        self.assertIn("B1-brief", msg)
        self.assertIn("gat", msg)

    def test_duplicate_dep_rejected(self) -> None:
        import json as _json

        raw = _json.loads(self.base_text)
        raw["nodes"]["B2-prd"]["deps"] = ["B1-brief", "B1-brief"]
        with self.assertRaises(self.PolicyError) as ctx:
            self.load_policy(_json.dumps(raw))
        msg = str(ctx.exception)
        self.assertIn("B2-prd", msg)
        self.assertIn("duplicate", msg)

    def test_entry_mode_mismatch_rejected(self) -> None:
        import json as _json

        raw = _json.loads(self.base_text)
        # B1-brief is greenfield-only; making it the brownfield entry must fail.
        raw["entry"]["brownfield"] = ["B1-brief"]
        with self.assertRaises(self.PolicyError) as ctx:
            self.load_policy(_json.dumps(raw))
        msg = str(ctx.exception)
        self.assertIn("brownfield", msg)
        self.assertIn("B1-brief", msg)


class PolicyRoundTripTests(unittest.TestCase):
    def setUp(self) -> None:
        from story_automator.core.lifecycle_policy import (
            canonical_policy_json,
            load_policy,
            policy_to_dict,
        )

        self.canonical_policy_json = canonical_policy_json
        self.load_policy = load_policy
        self.policy_to_dict = policy_to_dict
        self.text = (FIXTURE_DIR / "greenfield-minimal.policy.json").read_text(
            encoding="utf-8"
        )

    def test_load_then_to_dict_then_load_is_identity(self) -> None:
        import json as _json

        policy = self.load_policy(self.text)
        round_tripped = self.load_policy(_json.dumps(self.policy_to_dict(policy)))
        self.assertEqual(
            self.policy_to_dict(policy),
            self.policy_to_dict(round_tripped),
        )

    def test_canonical_form_is_sorted_and_separators_compact(self) -> None:
        policy = self.load_policy(self.text)
        canonical = self.canonical_policy_json(policy)
        self.assertNotIn(", ", canonical)
        self.assertNotIn(": ", canonical)
        self.assertTrue(canonical.startswith('{"entry":'))

    def test_canonical_form_stable_across_dict_orderings(self) -> None:
        import json as _json

        raw = _json.loads(self.text)
        permuted = {
            "entry": raw["entry"],
            "nodes": dict(reversed(list(raw["nodes"].items()))),
            "version": raw["version"],
        }
        a = self.load_policy(self.text)
        b = self.load_policy(_json.dumps(permuted))
        self.assertEqual(self.canonical_policy_json(a), self.canonical_policy_json(b))
