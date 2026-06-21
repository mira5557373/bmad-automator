from __future__ import annotations

import sys
import unittest
from pathlib import Path
from typing import Any


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


class VitestCollectorTests(unittest.TestCase):
    def test_config_fields(self) -> None:
        from story_automator.core.collectors.correctness import VITEST

        self.assertEqual(VITEST.collector_id, "vitest-correctness")
        self.assertEqual(VITEST.tool, "vitest")
        self.assertEqual(VITEST.category, "correctness")
        self.assertIn("*.ts", VITEST.file_patterns)

    def test_build_cmd(self) -> None:
        from story_automator.core.collectors.correctness import VITEST

        cmd = VITEST.build_cmd("/tmp/checkout", {})
        self.assertEqual(cmd, ["npx", "vitest", "run"])


class PlaywrightCollectorTests(unittest.TestCase):
    def test_config_fields(self) -> None:
        from story_automator.core.collectors.correctness import PLAYWRIGHT

        self.assertEqual(PLAYWRIGHT.collector_id, "playwright-correctness")
        self.assertEqual(PLAYWRIGHT.tool, "playwright")
        self.assertEqual(PLAYWRIGHT.category, "correctness")
        self.assertIn("*.ts", PLAYWRIGHT.file_patterns)

    def test_build_cmd(self) -> None:
        from story_automator.core.collectors.correctness import PLAYWRIGHT

        cmd = PLAYWRIGHT.build_cmd("/tmp/checkout", {})
        self.assertEqual(cmd, ["npx", "playwright", "test"])


class CorrectnessThreeCollectorsTests(unittest.TestCase):
    def test_three_collectors(self) -> None:
        from story_automator.core.collectors.correctness import COLLECTORS

        ids = {c.collector_id for c in COLLECTORS}
        self.assertIn("pytest-correctness", ids)
        self.assertIn("vitest-correctness", ids)
        self.assertIn("playwright-correctness", ids)


class CoverageCollectorTests(unittest.TestCase):
    def test_config_fields(self) -> None:
        from story_automator.core.collectors.correctness import COVERAGE

        self.assertEqual(COVERAGE.collector_id, "coverage-correctness")
        self.assertEqual(COVERAGE.tool, "python3")
        self.assertEqual(COVERAGE.category, "correctness")

    def test_build_cmd_invokes_coverage_script(self) -> None:
        from story_automator.core.collectors.correctness import COVERAGE

        profile: dict[str, Any] = {
            "matrix": {"P0": {"coverage_pct": 90, "levels": ["unit"]}},
        }
        cmd = COVERAGE.build_cmd("/tmp/co", profile)
        self.assertEqual(cmd[0], sys.executable)
        self.assertIn("coverage_check.py", cmd[1])
        self.assertTrue(Path(cmd[1]).is_file())
        self.assertEqual(cmd[2], "/tmp/co")
        self.assertEqual(cmd[3], "90")

    def test_build_cmd_default_threshold(self) -> None:
        from story_automator.core.collectors.correctness import COVERAGE

        cmd = COVERAGE.build_cmd("/tmp/co", {})
        self.assertEqual(cmd[3], "80")

    def test_build_cmd_uses_p0_coverage(self) -> None:
        from story_automator.core.collectors.correctness import COVERAGE

        profile: dict[str, Any] = {
            "matrix": {"P0": {"coverage_pct": 100, "levels": ["unit"]}},
        }
        cmd = COVERAGE.build_cmd("/tmp/co", profile)
        self.assertEqual(cmd[3], "100")


class CorrectnessFourCollectorsTests(unittest.TestCase):
    def test_four_collectors(self) -> None:
        from story_automator.core.collectors.correctness import COLLECTORS

        self.assertEqual(len(COLLECTORS), 4)
        ids = {c.collector_id for c in COLLECTORS}
        self.assertEqual(ids, {
            "pytest-correctness", "vitest-correctness",
            "playwright-correctness", "coverage-correctness",
        })
