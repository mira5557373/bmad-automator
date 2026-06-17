"""W0-M01 acceptance: schema round-trips; scheduler selects correct runnable
nodes; resume reconstructs state. Mirrors the build-spec-full.md §1 contract."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures" / "lifecycle"


class W0M01AcceptanceTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name)

    def test_schema_round_trips_greenfield(self) -> None:
        from story_automator.core.lifecycle_policy import (
            canonical_policy_json,
            load_policy,
            policy_to_dict,
        )

        text = (FIXTURE_DIR / "greenfield-minimal.policy.json").read_text(
            encoding="utf-8"
        )
        policy_a = load_policy(text)
        policy_b = load_policy(json.dumps(policy_to_dict(policy_a)))
        self.assertEqual(
            canonical_policy_json(policy_a), canonical_policy_json(policy_b)
        )

    def test_schema_round_trips_brownfield(self) -> None:
        from story_automator.core.lifecycle_policy import (
            canonical_policy_json,
            load_policy,
            policy_to_dict,
        )

        text = (FIXTURE_DIR / "brownfield-minimal.policy.json").read_text(
            encoding="utf-8"
        )
        policy_a = load_policy(text)
        policy_b = load_policy(json.dumps(policy_to_dict(policy_a)))
        self.assertEqual(
            canonical_policy_json(policy_a), canonical_policy_json(policy_b)
        )

    def test_scheduler_selects_correct_runnable_sequence(self) -> None:
        from story_automator.core.lifecycle_policy import load_policy
        from story_automator.core.lifecycle_scheduler import runnable_nodes
        from story_automator.core.lifecycle_status import NodeState, new_run_status

        policy = load_policy(
            (FIXTURE_DIR / "greenfield-minimal.policy.json").read_text(encoding="utf-8")
        )
        status = new_run_status(
            policy, run_id="r-acc", mode="greenfield",
            started_at="2026-06-17T10:00:00Z",
        )

        artifacts_present: set[str] = set()

        def exists(path: str) -> bool:
            return path in artifacts_present

        self.assertEqual(
            runnable_nodes(
                policy, status,
                artifact_exists=exists, max_concurrency=10,
            ),
            ["B1-brief"],
        )

        status.nodes["B1-brief"].state = NodeState.COMPLETE
        artifacts_present.add("docs/product-brief.md")

        self.assertEqual(
            runnable_nodes(
                policy, status,
                artifact_exists=exists, max_concurrency=10,
            ),
            ["B2-prd"],
        )

        status.nodes["B2-prd"].state = NodeState.COMPLETE
        artifacts_present.add("docs/prd.md")

        self.assertEqual(
            runnable_nodes(
                policy, status,
                artifact_exists=exists, max_concurrency=10,
            ),
            ["B3-arch"],
        )

        status.nodes["B3-arch"].state = NodeState.COMPLETE
        artifacts_present.add("docs/architecture.md")

        self.assertEqual(
            runnable_nodes(
                policy, status,
                artifact_exists=exists, max_concurrency=10,
            ),
            ["B3-epics"],
        )

        status.nodes["B3-epics"].state = NodeState.COMPLETE
        artifacts_present.add("epics/")
        self.assertEqual(
            runnable_nodes(
                policy, status,
                artifact_exists=exists, max_concurrency=10,
            ),
            [],
        )

    def test_resume_reconstructs_state_after_persist(self) -> None:
        from story_automator.core.lifecycle_policy import load_policy
        from story_automator.core.lifecycle_scheduler import runnable_nodes
        from story_automator.core.lifecycle_status import (
            ArtifactRecord,
            NodeState,
            load_status,
            new_run_status,
            save_status,
        )

        policy = load_policy(
            (FIXTURE_DIR / "greenfield-minimal.policy.json").read_text(encoding="utf-8")
        )
        status = new_run_status(
            policy, run_id="r-resume", mode="greenfield",
            started_at="2026-06-17T10:00:00Z",
        )

        status.nodes["B1-brief"].state = NodeState.COMPLETE
        status.artifacts["docs/product-brief.md"] = ArtifactRecord(
            path="docs/product-brief.md",
            produced_by_node="B1-brief",
            produced_at="2026-06-17T10:05:00Z",
            sha256="a" * 64,
        )

        target = self.dir / "lifecycle-status.json"
        save_status(target, status)

        revived = load_status(target, expected_policy=policy)

        out = runnable_nodes(
            policy, revived,
            artifact_exists={"docs/product-brief.md"}.__contains__,
            max_concurrency=10,
        )
        self.assertEqual(out, ["B2-prd"])
        self.assertEqual(
            revived.artifacts["docs/product-brief.md"].produced_by_node, "B1-brief"
        )

    def test_brownfield_scheduler_starts_at_b0_document_project(self) -> None:
        from story_automator.core.lifecycle_policy import load_policy
        from story_automator.core.lifecycle_scheduler import runnable_nodes
        from story_automator.core.lifecycle_status import new_run_status

        policy = load_policy(
            (FIXTURE_DIR / "brownfield-minimal.policy.json").read_text(encoding="utf-8")
        )
        status = new_run_status(
            policy, run_id="r-bf", mode="brownfield",
            started_at="2026-06-17T10:00:00Z",
        )
        out = runnable_nodes(
            policy, status,
            artifact_exists=lambda _p: False,
            max_concurrency=10,
        )
        self.assertEqual(out, ["B0-document-project"])
