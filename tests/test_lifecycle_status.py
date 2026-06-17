from __future__ import annotations

import json
import tempfile  # noqa: F401  (used in later test classes)
import unittest
from pathlib import Path

FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures" / "lifecycle"


class LifecycleStatusModuleTests(unittest.TestCase):
    def test_module_imports(self) -> None:
        from story_automator.core import lifecycle_status  # noqa: F401

    def test_exposes_policy_mismatch(self) -> None:
        from story_automator.core.lifecycle_status import PolicyMismatch

        self.assertTrue(issubclass(PolicyMismatch, ValueError))

    def test_exposes_node_state(self) -> None:
        from story_automator.core.lifecycle_status import NodeState

        self.assertEqual(NodeState.PENDING.value, "pending")
        self.assertEqual(NodeState.COMPLETE.value, "complete")


class StatusDataModelTests(unittest.TestCase):
    def test_all_node_states_enumerated(self) -> None:
        from story_automator.core.lifecycle_status import NodeState

        self.assertEqual(
            {member.value for member in NodeState},
            {
                "pending",
                "ready",
                "running",
                "awaiting_approval",
                "complete",
                "failed",
                "skipped",
            },
        )

    def test_node_run_defaults(self) -> None:
        from story_automator.core.lifecycle_status import NodeRun, NodeState

        run = NodeRun(state=NodeState.PENDING)
        self.assertEqual(run.state, NodeState.PENDING)
        self.assertEqual(run.attempts, 0)
        self.assertEqual(run.started_at, "")
        self.assertEqual(run.completed_at, "")
        self.assertEqual(run.last_error, "")
        self.assertIsNone(run.gate_decision)
        self.assertEqual(run.gate_notes, "")

    def test_artifact_record_fields(self) -> None:
        from story_automator.core.lifecycle_status import ArtifactRecord

        rec = ArtifactRecord(
            path="docs/prd.md",
            produced_by_node="B2-prd",
            produced_at="2026-06-17T10:00:00Z",
            sha256="0" * 64,
        )
        self.assertEqual(rec.path, "docs/prd.md")
        self.assertEqual(rec.produced_by_node, "B2-prd")

    def test_new_run_status_seeds_pending_per_node(self) -> None:
        from story_automator.core.lifecycle_policy import load_policy
        from story_automator.core.lifecycle_status import (
            NodeState,
            new_run_status,
        )

        text = (FIXTURE_DIR / "greenfield-minimal.policy.json").read_text(
            encoding="utf-8"
        )
        policy = load_policy(text)
        status = new_run_status(
            policy, run_id="run-abc", mode="greenfield", started_at="2026-06-17T10:00:00Z"
        )
        self.assertEqual(status.run_id, "run-abc")
        self.assertEqual(status.mode, "greenfield")
        self.assertEqual(status.started_at, "2026-06-17T10:00:00Z")
        self.assertEqual(set(status.nodes.keys()), set(policy.nodes.keys()))
        for node_id, run in status.nodes.items():
            self.assertEqual(run.state, NodeState.PENDING, msg=f"{node_id}")
        self.assertEqual(status.artifacts, {})

    def test_new_run_status_records_policy_hash(self) -> None:
        from story_automator.core.lifecycle_policy import canonical_policy_json, load_policy
        from story_automator.core.lifecycle_status import new_run_status

        import hashlib

        text = (FIXTURE_DIR / "greenfield-minimal.policy.json").read_text(
            encoding="utf-8"
        )
        policy = load_policy(text)
        status = new_run_status(
            policy, run_id="r1", mode="greenfield", started_at="2026-06-17T10:00:00Z"
        )
        expected = hashlib.sha256(canonical_policy_json(policy).encode("utf-8")).hexdigest()
        self.assertEqual(status.policy_hash, expected)

    def test_new_run_status_marks_out_of_mode_nodes_skipped(self) -> None:
        from story_automator.core.lifecycle_policy import load_policy
        from story_automator.core.lifecycle_status import NodeState, new_run_status

        raw = {
            "version": 1,
            "nodes": {
                "GF-only": {
                    "track": "bmm", "phase": 1, "skill": "bmad-noop",
                    "validator_skill": None, "deps": [], "input_artifacts": [],
                    "output_artifact": "docs/gf.md", "verifier": "structural",
                    "gate": "auto", "modes": ["greenfield"],
                    "agent_role": "analyst", "interactive": False,
                },
                "BF-only": {
                    "track": "bmm", "phase": 1, "skill": "bmad-noop",
                    "validator_skill": None, "deps": [], "input_artifacts": [],
                    "output_artifact": "docs/bf.md", "verifier": "structural",
                    "gate": "auto", "modes": ["brownfield"],
                    "agent_role": "analyst", "interactive": False,
                },
                "Both": {
                    "track": "bmm", "phase": 1, "skill": "bmad-noop",
                    "validator_skill": None, "deps": [], "input_artifacts": [],
                    "output_artifact": "docs/both.md", "verifier": "structural",
                    "gate": "auto", "modes": ["greenfield", "brownfield"],
                    "agent_role": "analyst", "interactive": False,
                },
            },
            "entry": {"greenfield": ["GF-only"], "brownfield": ["BF-only"]},
        }
        policy = load_policy(json.dumps(raw))
        status = new_run_status(
            policy, run_id="r", mode="greenfield", started_at="2026-06-17T10:00:00Z"
        )
        self.assertEqual(status.nodes["GF-only"].state, NodeState.PENDING)
        self.assertEqual(status.nodes["Both"].state, NodeState.PENDING)
        self.assertEqual(status.nodes["BF-only"].state, NodeState.SKIPPED)

    def test_new_run_status_rejects_unknown_mode(self) -> None:
        from story_automator.core.lifecycle_policy import load_policy
        from story_automator.core.lifecycle_status import new_run_status

        policy = load_policy(
            (FIXTURE_DIR / "greenfield-minimal.policy.json").read_text(encoding="utf-8")
        )
        with self.assertRaises(ValueError):
            new_run_status(
                policy, run_id="r", mode="midfield", started_at="2026-06-17T10:00:00Z"
            )
