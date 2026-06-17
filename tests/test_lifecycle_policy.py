from __future__ import annotations

import unittest


class LifecyclePolicyModuleTests(unittest.TestCase):
    def test_module_imports(self) -> None:
        from story_automator.core import lifecycle_policy  # noqa: F401

    def test_exposes_policy_error(self) -> None:
        from story_automator.core.lifecycle_policy import PolicyError

        self.assertTrue(issubclass(PolicyError, ValueError))

    def test_exposes_load_policy(self) -> None:
        from story_automator.core.lifecycle_policy import load_policy

        self.assertTrue(callable(load_policy))
