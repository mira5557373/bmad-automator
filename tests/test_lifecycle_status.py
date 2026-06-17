from __future__ import annotations

import unittest


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
