"""W0-M02 acceptance: runs a node end-to-end (mocked agent) → verify → advance;
phase-4 delegates; events emit; mirrors `tests/test_orchestration_loop.py`."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from story_automator.core.lifecycle_events import (
    LifecyclePhaseCompleted,
    LifecyclePhaseStarted,
)
from story_automator.core.lifecycle_policy import load_policy
from story_automator.core.lifecycle_runner import run_next_node
from story_automator.core.lifecycle_status import (
    NodeState,
    load_status,
    new_run_status,
    save_status,
)
from story_automator.core.telemetry_emitter import TelemetryEmitter
from story_automator.core.telemetry_reader import TelemetryReader

FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures" / "lifecycle"


class W0M02AcceptanceTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.status_path = self.root / "lifecycle-status.json"

    def test_two_node_run_advances_through_complete(self) -> None:
        policy = load_policy(
            (FIXTURE_DIR / "m02-two-node.policy.json").read_text(
                encoding="utf-8"
            )
        )
        status = new_run_status(
            policy,
            run_id="acc-m02",
            mode="greenfield",
            started_at="2026-06-17T00:00:00Z",
        )
        save_status(self.status_path, status)

        emitter = TelemetryEmitter(self.root / "telemetry" / "events.jsonl")

        def fake_spawn(session, command, agent, project_root, mode=None):
            for nid, node in policy.nodes.items():
                if nid in session:
                    target = Path(project_root) / node.output_artifact
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_text(f"# {nid}\n", encoding="utf-8")
                    break
            return ("", 0)

        results: list = []
        for _ in range(3):
            r = run_next_node(
                policy,
                status,
                project_root=str(self.root),
                status_path=self.status_path,
                spawn_agent=fake_spawn,
                monitor_session=lambda args: 0,
                emitter=emitter,
            )
            results.append(r)
            if r is None:
                break

        node_ids = [r.node_id for r in results if r is not None]
        final_states = [r.final_state for r in results if r is not None]
        self.assertEqual(node_ids, ["N1-first", "N2-second"])
        self.assertEqual(final_states, ["complete", "complete"])
        self.assertIsNone(results[-1])

        revived = load_status(self.status_path)
        self.assertEqual(revived.nodes["N1-first"].state, NodeState.COMPLETE)
        self.assertEqual(revived.nodes["N2-second"].state, NodeState.COMPLETE)

        events = list(
            TelemetryReader(
                self.root / "telemetry" / "events.jsonl"
            ).iter_events()
        )
        types = [type(e).__name__ for e in events]
        self.assertEqual(types.count("LifecyclePhaseStarted"), 2)
        self.assertEqual(types.count("LifecyclePhaseCompleted"), 2)
        for e in events:
            if isinstance(e, LifecyclePhaseStarted):
                self.assertIn(e.node_id, {"N1-first", "N2-second"})
            if isinstance(e, LifecyclePhaseCompleted):
                self.assertEqual(e.gate_decision, "auto_complete")

    def test_phase4_delegate_path_advances_and_emits(self) -> None:
        policy = load_policy(
            (FIXTURE_DIR / "m02-phase4-delegate.policy.json").read_text(
                encoding="utf-8"
            )
        )
        status = new_run_status(
            policy,
            run_id="acc-m02-p4",
            mode="greenfield",
            started_at="2026-06-17T00:00:00Z",
        )
        (self.root / "epics").mkdir()
        (self.root / "epics" / "e1.md").write_text(
            "# e1\n", encoding="utf-8"
        )
        status.nodes["B3-epics"].state = NodeState.COMPLETE
        save_status(self.status_path, status)

        emitter = TelemetryEmitter(self.root / "telemetry" / "events.jsonl")

        delegate_invocations: list[str] = []

        def stub_delegate(*, node, project_root, status, run_id):
            delegate_invocations.append(node.id)
            (Path(project_root) / node.output_artifact).write_text(
                "stories: []\n", encoding="utf-8"
            )
            return {"verified": True}

        def never_spawn(*a, **k):
            raise AssertionError(
                "spawn_agent must not be invoked for track=bmm phase=4"
            )

        result = run_next_node(
            policy,
            status,
            project_root=str(self.root),
            status_path=self.status_path,
            spawn_agent=never_spawn,
            monitor_session=lambda args: 0,
            sprint_delegate=stub_delegate,
            emitter=emitter,
        )

        self.assertEqual(result.node_id, "B4-sprint")
        self.assertEqual(result.final_state, "complete")
        self.assertEqual(delegate_invocations, ["B4-sprint"])

        events = list(
            TelemetryReader(
                self.root / "telemetry" / "events.jsonl"
            ).iter_events()
        )
        types = [
            (type(e).__name__, getattr(e, "node_id", "")) for e in events
        ]
        self.assertIn(("LifecyclePhaseStarted", "B4-sprint"), types)
        self.assertIn(("LifecyclePhaseCompleted", "B4-sprint"), types)


if __name__ == "__main__":
    unittest.main()
