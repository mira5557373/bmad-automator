from __future__ import annotations

import unittest


class LifecycleSchedulerModuleTests(unittest.TestCase):
    def test_module_imports(self) -> None:
        from story_automator.core import lifecycle_scheduler  # noqa: F401

    def test_exposes_scheduler_error(self) -> None:
        from story_automator.core.lifecycle_scheduler import SchedulerError

        self.assertTrue(issubclass(SchedulerError, RuntimeError))

    def test_exposes_runnable_nodes(self) -> None:
        from story_automator.core.lifecycle_scheduler import runnable_nodes

        self.assertTrue(callable(runnable_nodes))
