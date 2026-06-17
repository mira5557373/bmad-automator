from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from typing import Any  # noqa: F401 — used in later test classes


class LifecycleRunnerModuleTests(unittest.TestCase):
    def test_module_imports(self) -> None:
        from story_automator.core import lifecycle_runner  # noqa: F401

    def test_exposes_runner_error(self) -> None:
        from story_automator.core.lifecycle_runner import RunnerError

        self.assertTrue(issubclass(RunnerError, RuntimeError))

    def test_exposes_run_result(self) -> None:
        from story_automator.core.lifecycle_runner import RunResult

        r = RunResult(
            node_id="B1-brief",
            final_state="complete",
            verified=True,
            reason="",
            duration_s=0.0,
        )
        self.assertEqual(r.node_id, "B1-brief")
        self.assertEqual(r.final_state, "complete")

    def test_exposes_run_next_node(self) -> None:
        from story_automator.core.lifecycle_runner import run_next_node

        self.assertTrue(callable(run_next_node))


class StateTransitionPrimitiveTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)

    def _seed(self, run_id: str):
        from story_automator.core.lifecycle_policy import load_policy
        from story_automator.core.lifecycle_status import (
            new_run_status,
            save_status,
        )

        fixture = (
            Path(__file__).resolve().parent
            / "fixtures"
            / "lifecycle"
            / "greenfield-minimal.policy.json"
        )
        policy = load_policy(fixture.read_text(encoding="utf-8"))
        status = new_run_status(
            policy,
            run_id=run_id,
            mode="greenfield",
            started_at="2026-06-17T00:00:00Z",
        )
        status_path = self.root / "lifecycle-status.json"
        save_status(status_path, status)
        return policy, status, status_path

    def test_transition_persists_status_atomically(self) -> None:
        from story_automator.core.lifecycle_runner import _transition_node
        from story_automator.core.lifecycle_status import (
            NodeState,
            load_status,
        )

        _policy, status, status_path = self._seed("r-t6")
        _transition_node(
            status,
            status_path,
            "B1-brief",
            NodeState.RUNNING,
            started_at="2026-06-17T00:00:01Z",
        )
        revived = load_status(status_path)
        self.assertEqual(revived.nodes["B1-brief"].state, NodeState.RUNNING)
        self.assertEqual(
            revived.nodes["B1-brief"].started_at, "2026-06-17T00:00:01Z"
        )

    def test_transition_to_complete_records_completed_at(self) -> None:
        from story_automator.core.lifecycle_runner import _transition_node
        from story_automator.core.lifecycle_status import (
            NodeState,
            load_status,
        )

        _policy, status, status_path = self._seed("r-t6c")
        _transition_node(
            status,
            status_path,
            "B1-brief",
            NodeState.COMPLETE,
            completed_at="2026-06-17T00:01:00Z",
        )
        revived = load_status(status_path)
        self.assertEqual(revived.nodes["B1-brief"].state, NodeState.COMPLETE)
        self.assertEqual(
            revived.nodes["B1-brief"].completed_at, "2026-06-17T00:01:00Z"
        )

    def test_transition_to_failed_records_last_error(self) -> None:
        from story_automator.core.lifecycle_runner import _transition_node
        from story_automator.core.lifecycle_status import (
            NodeState,
            load_status,
        )

        _policy, status, status_path = self._seed("r-t6f")
        _transition_node(
            status,
            status_path,
            "B1-brief",
            NodeState.FAILED,
            last_error="agent_crashed: exit_code_2",
            completed_at="2026-06-17T00:01:00Z",
        )
        revived = load_status(status_path)
        self.assertEqual(revived.nodes["B1-brief"].state, NodeState.FAILED)
        self.assertIn(
            "agent_crashed", revived.nodes["B1-brief"].last_error
        )


class SpawnPathTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.status_path = self.root / "lifecycle-status.json"
        from story_automator.core.lifecycle_policy import load_policy
        from story_automator.core.lifecycle_status import (
            new_run_status,
            save_status,
        )

        fixture = (
            Path(__file__).resolve().parent
            / "fixtures"
            / "lifecycle"
            / "greenfield-minimal.policy.json"
        )
        self.policy = load_policy(fixture.read_text(encoding="utf-8"))
        self.status = new_run_status(
            self.policy,
            run_id="r-spawn",
            mode="greenfield",
            started_at="2026-06-17T00:00:00Z",
        )
        save_status(self.status_path, self.status)

    def test_picks_first_runnable_node_and_spawns(self) -> None:
        from story_automator.core.lifecycle_runner import run_next_node

        spawn_calls: list = []
        monitor_calls: list = []

        def stub_spawn(session, command, agent, project_root, mode=None):
            spawn_calls.append((session, command, agent))
            return ("", 0)

        def stub_monitor(args):
            monitor_calls.append(tuple(args))
            return 0

        result = run_next_node(
            self.policy,
            self.status,
            project_root=str(self.root),
            status_path=self.status_path,
            spawn_agent=stub_spawn,
            monitor_session=stub_monitor,
            verifier_dispatch=lambda name, **kw: {"verified": True},
        )
        self.assertIsNotNone(result)
        self.assertEqual(result.node_id, "B1-brief")
        self.assertEqual(len(spawn_calls), 1)
        self.assertIn("B1-brief", spawn_calls[0][0])
        self.assertEqual(len(monitor_calls), 1)

    def test_no_runnable_nodes_returns_none(self) -> None:
        from story_automator.core.lifecycle_runner import run_next_node
        from story_automator.core.lifecycle_status import (
            NodeState,
            save_status,
        )

        for node_id in self.status.nodes:
            self.status.nodes[node_id].state = NodeState.COMPLETE
        save_status(self.status_path, self.status)

        result = run_next_node(
            self.policy,
            self.status,
            project_root=str(self.root),
            status_path=self.status_path,
            spawn_agent=lambda *a, **k: ("", 0),
            monitor_session=lambda *a, **k: 0,
        )
        self.assertIsNone(result)

    def test_status_marks_running_before_spawn(self) -> None:
        from story_automator.core.lifecycle_runner import run_next_node
        from story_automator.core.lifecycle_status import (
            NodeState,
            load_status,
        )

        observed_states_at_spawn: list = []

        def spy_spawn(session, command, agent, project_root, mode=None):
            on_disk = load_status(self.status_path)
            observed_states_at_spawn.append(
                on_disk.nodes["B1-brief"].state
            )
            return ("", 0)

        run_next_node(
            self.policy,
            self.status,
            project_root=str(self.root),
            status_path=self.status_path,
            spawn_agent=spy_spawn,
            monitor_session=lambda *a, **k: 0,
            verifier_dispatch=lambda name, **kw: {"verified": True},
        )
        self.assertEqual(observed_states_at_spawn, [NodeState.RUNNING])

    def test_running_node_is_not_selected_by_scheduler(self) -> None:
        from story_automator.core.lifecycle_runner import run_next_node
        from story_automator.core.lifecycle_status import (
            NodeState,
            save_status,
        )

        self.status.nodes["B1-brief"].state = NodeState.RUNNING
        save_status(self.status_path, self.status)

        result = run_next_node(
            self.policy,
            self.status,
            project_root=str(self.root),
            status_path=self.status_path,
            spawn_agent=lambda *a, **k: ("", 0),
            monitor_session=lambda *a, **k: 0,
            verifier_dispatch=lambda name, **kw: {"verified": True},
        )
        self.assertIsNone(result)

    def test_spawn_failure_transitions_to_failed(self) -> None:
        from story_automator.core.lifecycle_runner import run_next_node
        from story_automator.core.lifecycle_status import (
            NodeState,
            load_status,
        )

        def failing_spawn(session, command, agent, project_root, mode=None):
            return ("tmux: command not found\n", 127)

        result = run_next_node(
            self.policy,
            self.status,
            project_root=str(self.root),
            status_path=self.status_path,
            spawn_agent=failing_spawn,
            monitor_session=lambda *a, **k: 0,
        )
        self.assertEqual(result.final_state, "failed")
        self.assertFalse(result.verified)
        on_disk = load_status(self.status_path)
        self.assertEqual(on_disk.nodes["B1-brief"].state, NodeState.FAILED)
        self.assertIn("spawn", on_disk.nodes["B1-brief"].last_error)


if __name__ == "__main__":
    unittest.main()
