from __future__ import annotations

import unittest


class RuffCollectorTests(unittest.TestCase):
    def test_config_fields(self) -> None:
        from story_automator.core.collectors.static import RUFF

        self.assertEqual(RUFF.collector_id, "ruff-static")
        self.assertEqual(RUFF.tool, "ruff")
        self.assertEqual(RUFF.category, "static")
        self.assertTrue(RUFF.deterministic)
        self.assertIn("*.py", RUFF.file_patterns)

    def test_build_cmd(self) -> None:
        from story_automator.core.collectors.static import RUFF

        cmd = RUFF.build_cmd("/tmp/checkout", {})
        self.assertEqual(cmd[0], "ruff")
        self.assertIn("check", cmd)
        self.assertIn(".", cmd)

    def test_version_cmd(self) -> None:
        from story_automator.core.collectors.static import RUFF

        self.assertIsNotNone(RUFF.tool_version_cmd)
        self.assertIn("ruff", RUFF.tool_version_cmd)


class MypyCollectorTests(unittest.TestCase):
    def test_config_fields(self) -> None:
        from story_automator.core.collectors.static import MYPY

        self.assertEqual(MYPY.collector_id, "mypy-static")
        self.assertEqual(MYPY.tool, "mypy")
        self.assertEqual(MYPY.category, "static")
        self.assertIn("*.py", MYPY.file_patterns)
        self.assertIn("*.pyi", MYPY.file_patterns)

    def test_build_cmd(self) -> None:
        from story_automator.core.collectors.static import MYPY

        cmd = MYPY.build_cmd("/tmp/checkout", {})
        self.assertEqual(cmd[0], "mypy")
        self.assertIn(".", cmd)

    def test_version_cmd(self) -> None:
        from story_automator.core.collectors.static import MYPY

        self.assertIsNotNone(MYPY.tool_version_cmd)
        self.assertIn("mypy", MYPY.tool_version_cmd)


class StaticCollectorListTests(unittest.TestCase):
    def test_ruff_and_mypy_present(self) -> None:
        from story_automator.core.collectors.static import COLLECTORS

        ids = {c.collector_id for c in COLLECTORS}
        self.assertIn("ruff-static", ids)
        self.assertIn("mypy-static", ids)

    def test_all_static_category(self) -> None:
        from story_automator.core.collectors.static import COLLECTORS

        for c in COLLECTORS:
            self.assertEqual(c.category, "static")

    def test_unique_collector_ids(self) -> None:
        from story_automator.core.collectors.static import COLLECTORS

        ids = [c.collector_id for c in COLLECTORS]
        self.assertEqual(len(ids), len(set(ids)))
