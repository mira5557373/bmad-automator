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


class TscCollectorTests(unittest.TestCase):
    def test_config_fields(self) -> None:
        from story_automator.core.collectors.static import TSC

        self.assertEqual(TSC.collector_id, "tsc-static")
        self.assertEqual(TSC.tool, "tsc")
        self.assertEqual(TSC.category, "static")
        self.assertIn("*.ts", TSC.file_patterns)
        self.assertIn("*.tsx", TSC.file_patterns)

    def test_build_cmd(self) -> None:
        from story_automator.core.collectors.static import TSC

        cmd = TSC.build_cmd("/tmp/checkout", {})
        self.assertEqual(cmd, ["npx", "tsc", "--noEmit"])


class BiomeCollectorTests(unittest.TestCase):
    def test_config_fields(self) -> None:
        from story_automator.core.collectors.static import BIOME

        self.assertEqual(BIOME.collector_id, "biome-static")
        self.assertEqual(BIOME.tool, "biome")
        self.assertEqual(BIOME.category, "static")
        self.assertIn("*.ts", BIOME.file_patterns)
        self.assertIn("*.js", BIOME.file_patterns)

    def test_build_cmd(self) -> None:
        from story_automator.core.collectors.static import BIOME

        cmd = BIOME.build_cmd("/tmp/checkout", {})
        self.assertEqual(cmd, ["npx", "@biomejs/biome", "check", "."])


class KnipCollectorTests(unittest.TestCase):
    def test_config_fields(self) -> None:
        from story_automator.core.collectors.static import KNIP

        self.assertEqual(KNIP.collector_id, "knip-static")
        self.assertEqual(KNIP.tool, "knip")
        self.assertEqual(KNIP.category, "static")

    def test_build_cmd(self) -> None:
        from story_automator.core.collectors.static import KNIP

        cmd = KNIP.build_cmd("/tmp/checkout", {})
        self.assertEqual(cmd, ["npx", "knip"])


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


class StaticCollectorFullListTests(unittest.TestCase):
    def test_five_collectors(self) -> None:
        from story_automator.core.collectors.static import COLLECTORS

        self.assertEqual(len(COLLECTORS), 5)

    def test_all_expected_ids(self) -> None:
        from story_automator.core.collectors.static import COLLECTORS

        ids = {c.collector_id for c in COLLECTORS}
        self.assertEqual(ids, {
            "ruff-static", "mypy-static", "tsc-static",
            "biome-static", "knip-static",
        })
