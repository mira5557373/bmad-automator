from __future__ import annotations

import unittest


class PytestCollectorTests(unittest.TestCase):
    def test_config_fields(self) -> None:
        from story_automator.core.collectors.correctness import PYTEST

        self.assertEqual(PYTEST.collector_id, "pytest-correctness")
        self.assertEqual(PYTEST.tool, "pytest")
        self.assertEqual(PYTEST.category, "correctness")
        self.assertTrue(PYTEST.deterministic)
        self.assertIn("*.py", PYTEST.file_patterns)

    def test_build_cmd(self) -> None:
        from story_automator.core.collectors.correctness import PYTEST

        cmd = PYTEST.build_cmd("/tmp/checkout", {})
        self.assertEqual(cmd[0], "pytest")
        self.assertIn("--tb=short", cmd)
        self.assertIn("-q", cmd)

    def test_version_cmd(self) -> None:
        from story_automator.core.collectors.correctness import PYTEST

        self.assertIsNotNone(PYTEST.tool_version_cmd)
        self.assertIn("pytest", PYTEST.tool_version_cmd)


class CorrectnessCollectorListTests(unittest.TestCase):
    def test_pytest_present(self) -> None:
        from story_automator.core.collectors.correctness import COLLECTORS

        ids = {c.collector_id for c in COLLECTORS}
        self.assertIn("pytest-correctness", ids)

    def test_all_correctness_category(self) -> None:
        from story_automator.core.collectors.correctness import COLLECTORS

        for c in COLLECTORS:
            self.assertEqual(c.category, "correctness")

    def test_unique_collector_ids(self) -> None:
        from story_automator.core.collectors.correctness import COLLECTORS

        ids = [c.collector_id for c in COLLECTORS]
        self.assertEqual(len(ids), len(set(ids)))
