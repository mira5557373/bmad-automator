from __future__ import annotations

import unittest
from pathlib import Path

FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures" / "lifecycle"


class LifecycleSchedulerModuleTests(unittest.TestCase):
    def test_module_imports(self) -> None:
        from story_automator.core import lifecycle_scheduler  # noqa: F401

    def test_exposes_scheduler_error(self) -> None:
        from story_automator.core.lifecycle_scheduler import SchedulerError

        self.assertTrue(issubclass(SchedulerError, RuntimeError))

    def test_exposes_runnable_nodes(self) -> None:
        from story_automator.core.lifecycle_scheduler import runnable_nodes

        self.assertTrue(callable(runnable_nodes))


class TopologicalOrderTests(unittest.TestCase):
    def setUp(self) -> None:
        from story_automator.core.lifecycle_policy import load_policy

        self.policy = load_policy(
            (FIXTURE_DIR / "greenfield-minimal.policy.json").read_text(encoding="utf-8")
        )

    def test_linear_chain_emits_in_dep_order(self) -> None:
        from story_automator.core.lifecycle_scheduler import topological_order

        order = topological_order(self.policy, mode="greenfield")
        self.assertEqual(order, ["B1-brief", "B2-prd", "B3-arch", "B3-epics"])

    def test_topo_order_lexicographic_when_independent(self) -> None:
        import json as _json

        from story_automator.core.lifecycle_policy import load_policy
        from story_automator.core.lifecycle_scheduler import topological_order

        nodes_decl_order = ["Z-third", "A-first", "M-second"]
        raw = {
            "version": 1,
            "nodes": {
                name: {
                    "track": "bmm",
                    "phase": 1,
                    "skill": "bmad-noop",
                    "validator_skill": None,
                    "deps": [],
                    "input_artifacts": [],
                    "output_artifact": f"docs/{name}.md",
                    "verifier": "structural",
                    "gate": "auto",
                    "modes": ["greenfield"],
                    "agent_role": "analyst",
                    "interactive": False,
                }
                for name in nodes_decl_order
            },
            "entry": {"greenfield": ["A-first"], "brownfield": []},
        }
        policy = load_policy(_json.dumps(raw))
        self.assertEqual(
            topological_order(policy, mode="greenfield"),
            ["A-first", "M-second", "Z-third"],
        )

    def test_topo_order_filters_out_of_mode_nodes(self) -> None:
        import json as _json

        from story_automator.core.lifecycle_policy import load_policy
        from story_automator.core.lifecycle_scheduler import topological_order

        raw = {
            "version": 1,
            "nodes": {
                "B0-document": {
                    "track": "bmm",
                    "phase": 0,
                    "skill": "bmad-document-project",
                    "validator_skill": None,
                    "deps": [],
                    "input_artifacts": [],
                    "output_artifact": "docs/context.md",
                    "verifier": "structural",
                    "gate": "auto",
                    "modes": ["brownfield"],
                    "agent_role": "analyst",
                    "interactive": False,
                },
                "B1-brief": {
                    "track": "bmm",
                    "phase": 1,
                    "skill": "bmad-product-brief",
                    "validator_skill": None,
                    "deps": [],
                    "input_artifacts": [],
                    "output_artifact": "docs/product-brief.md",
                    "verifier": "structural",
                    "gate": "human",
                    "modes": ["greenfield", "brownfield"],
                    "agent_role": "analyst",
                    "interactive": True,
                },
            },
            "entry": {"greenfield": ["B1-brief"], "brownfield": ["B0-document"]},
        }
        policy = load_policy(_json.dumps(raw))
        self.assertEqual(topological_order(policy, mode="greenfield"), ["B1-brief"])
        self.assertEqual(
            topological_order(policy, mode="brownfield"),
            ["B0-document", "B1-brief"],
        )

    def test_topo_order_invalid_mode_raises(self) -> None:
        from story_automator.core.lifecycle_scheduler import (
            SchedulerError,
            topological_order,
        )

        with self.assertRaises(SchedulerError):
            topological_order(self.policy, mode="bogus")

    def test_topo_order_empty_active_set_returns_empty_list(self) -> None:
        from story_automator.core.lifecycle_scheduler import topological_order

        self.assertEqual(topological_order(self.policy, mode="brownfield"), [])
