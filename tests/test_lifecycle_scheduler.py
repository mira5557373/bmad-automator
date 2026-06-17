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


class RunnableNodesTests(unittest.TestCase):
    def setUp(self) -> None:
        from story_automator.core.lifecycle_policy import load_policy
        from story_automator.core.lifecycle_status import new_run_status

        self.policy = load_policy(
            (FIXTURE_DIR / "greenfield-minimal.policy.json").read_text(encoding="utf-8")
        )
        self.status = new_run_status(
            self.policy,
            run_id="r-7",
            mode="greenfield",
            started_at="2026-06-17T10:00:00Z",
        )

    def test_initial_state_only_entry_node_is_runnable(self) -> None:
        from story_automator.core.lifecycle_scheduler import runnable_nodes

        out = runnable_nodes(
            self.policy,
            self.status,
            artifact_exists=lambda _path: False,
            max_concurrency=10,
        )
        self.assertEqual(out, ["B1-brief"])

    def test_node_blocked_until_deps_complete(self) -> None:
        from story_automator.core.lifecycle_scheduler import runnable_nodes
        from story_automator.core.lifecycle_status import NodeState

        out = runnable_nodes(
            self.policy,
            self.status,
            artifact_exists=lambda _path: True,
            max_concurrency=10,
        )
        self.assertEqual(out, ["B1-brief"])

        self.status.nodes["B1-brief"].state = NodeState.COMPLETE
        out2 = runnable_nodes(
            self.policy,
            self.status,
            artifact_exists=lambda path: path == "docs/product-brief.md",
            max_concurrency=10,
        )
        self.assertEqual(out2, ["B2-prd"])

    def test_node_blocked_when_input_artifact_missing(self) -> None:
        from story_automator.core.lifecycle_scheduler import runnable_nodes
        from story_automator.core.lifecycle_status import NodeState

        self.status.nodes["B1-brief"].state = NodeState.COMPLETE
        out = runnable_nodes(
            self.policy,
            self.status,
            artifact_exists=lambda _path: False,
            max_concurrency=10,
        )
        self.assertEqual(out, [])

    def test_complete_and_failed_nodes_never_returned(self) -> None:
        from story_automator.core.lifecycle_scheduler import runnable_nodes
        from story_automator.core.lifecycle_status import NodeState

        self.status.nodes["B1-brief"].state = NodeState.COMPLETE
        self.status.nodes["B2-prd"].state = NodeState.FAILED
        out = runnable_nodes(
            self.policy,
            self.status,
            artifact_exists=lambda _p: True,
            max_concurrency=10,
        )
        self.assertEqual(out, [])

    def test_running_node_is_not_returned_again(self) -> None:
        from story_automator.core.lifecycle_scheduler import runnable_nodes
        from story_automator.core.lifecycle_status import NodeState

        self.status.nodes["B1-brief"].state = NodeState.RUNNING
        out = runnable_nodes(
            self.policy,
            self.status,
            artifact_exists=lambda _p: True,
            max_concurrency=10,
        )
        self.assertEqual(out, [])

    def test_awaiting_approval_blocks_downstream(self) -> None:
        from story_automator.core.lifecycle_scheduler import runnable_nodes
        from story_automator.core.lifecycle_status import NodeState

        self.status.nodes["B1-brief"].state = NodeState.AWAITING_APPROVAL
        out = runnable_nodes(
            self.policy,
            self.status,
            artifact_exists=lambda _p: True,
            max_concurrency=10,
        )
        self.assertEqual(out, [])


class ConcurrencyCapTests(unittest.TestCase):
    def _diamond_policy(self):
        import json as _json

        from story_automator.core.lifecycle_policy import load_policy

        raw = {
            "version": 1,
            "nodes": {
                "B1": {
                    "track": "bmm",
                    "phase": 1,
                    "skill": "bmad-noop",
                    "validator_skill": None,
                    "deps": [],
                    "input_artifacts": [],
                    "output_artifact": "docs/b1.md",
                    "verifier": "structural",
                    "gate": "auto",
                    "modes": ["greenfield"],
                    "agent_role": "analyst",
                    "interactive": False,
                },
                **{
                    name: {
                        "track": "bmm",
                        "phase": 2,
                        "skill": "bmad-noop",
                        "validator_skill": None,
                        "deps": ["B1"],
                        "input_artifacts": ["docs/b1.md"],
                        "output_artifact": f"docs/{name}.md",
                        "verifier": "structural",
                        "gate": "auto",
                        "modes": ["greenfield"],
                        "agent_role": "analyst",
                        "interactive": False,
                    }
                    for name in ("B2a", "B2b", "B2c")
                },
            },
            "entry": {"greenfield": ["B1"], "brownfield": []},
        }
        return load_policy(_json.dumps(raw))

    def test_cap_limits_returned_runnable_set(self) -> None:
        from story_automator.core.lifecycle_scheduler import runnable_nodes
        from story_automator.core.lifecycle_status import NodeState, new_run_status

        policy = self._diamond_policy()
        status = new_run_status(
            policy, run_id="r-c", mode="greenfield", started_at="2026-06-17T10:00:00Z"
        )
        status.nodes["B1"].state = NodeState.COMPLETE

        out = runnable_nodes(
            policy,
            status,
            artifact_exists=lambda _p: True,
            max_concurrency=2,
        )
        self.assertEqual(out, ["B2a", "B2b"])

        out1 = runnable_nodes(
            policy,
            status,
            artifact_exists=lambda _p: True,
            max_concurrency=1,
        )
        self.assertEqual(out1, ["B2a"])

        out_all = runnable_nodes(
            policy,
            status,
            artifact_exists=lambda _p: True,
            max_concurrency=10,
        )
        self.assertEqual(out_all, ["B2a", "B2b", "B2c"])

    def test_cap_zero_raises(self) -> None:
        from story_automator.core.lifecycle_scheduler import (
            SchedulerError,
            runnable_nodes,
        )
        from story_automator.core.lifecycle_status import new_run_status

        policy = self._diamond_policy()
        status = new_run_status(
            policy, run_id="r-c", mode="greenfield", started_at="2026-06-17T10:00:00Z"
        )
        with self.assertRaises(SchedulerError):
            runnable_nodes(
                policy,
                status,
                artifact_exists=lambda _p: True,
                max_concurrency=0,
            )
