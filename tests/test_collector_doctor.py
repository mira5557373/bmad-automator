from __future__ import annotations

import sys
import unittest
from typing import Any

from story_automator.core.collector_config import CollectorConfig
from story_automator.core.collector_doctor import (
    DoctorResult,
    check_collector_available,
    preflight_check,
)
from story_automator.core.collector_registry import CollectorRegistry


def _noop_cmd(checkout: str, profile: dict[str, Any]) -> list[str]:
    return [sys.executable, "-c", "pass"]


def _make_config(
    collector_id: str = "test",
    tool: str = "python3",
    category: str = "correctness",
    version_cmd: tuple[str, ...] | None = None,
) -> CollectorConfig:
    return CollectorConfig(
        collector_id=collector_id,
        tool=tool,
        category=category,
        build_cmd=_noop_cmd,
        tool_version_cmd=version_cmd,
    )


class CheckCollectorAvailableTests(unittest.TestCase):
    def test_available_tool(self) -> None:
        cfg = _make_config(tool="python3")
        result = check_collector_available(cfg)
        self.assertTrue(result.available)
        self.assertEqual(result.tool, "python3")
        self.assertEqual(result.message, "ok")

    def test_unavailable_tool(self) -> None:
        cfg = _make_config(tool="nonexistent-tool-xyz-999")
        result = check_collector_available(cfg)
        self.assertFalse(result.available)
        self.assertIn("not found", result.message)

    def test_version_cmd_populates_version(self) -> None:
        cfg = _make_config(
            tool="python3",
            version_cmd=(sys.executable, "--version"),
        )
        result = check_collector_available(cfg)
        self.assertTrue(result.available)
        self.assertIn("Python", result.version)

    def test_no_version_cmd_leaves_version_empty(self) -> None:
        cfg = _make_config(tool="python3")
        result = check_collector_available(cfg)
        self.assertEqual(result.version, "")

    def test_version_cmd_failure_still_available(self) -> None:
        cfg = _make_config(
            tool="python3",
            version_cmd=(sys.executable, "-c", "import sys; sys.exit(1)"),
        )
        result = check_collector_available(cfg)
        self.assertTrue(result.available)
        self.assertEqual(result.version, "")

    def test_result_is_frozen(self) -> None:
        result = DoctorResult(
            tool="t", available=True, version="1.0", message="ok",
        )
        with self.assertRaises(AttributeError):
            result.tool = "mutated"  # type: ignore[misc]


class PreflightCheckTests(unittest.TestCase):
    def _profile(self, cats: list[str]) -> dict[str, Any]:
        return {
            "categories": {"code": cats, "system": []},
            "categories_na": [],
            "rules": {},
        }

    def test_all_available(self) -> None:
        reg = CollectorRegistry()
        reg.register(_make_config("a", "python3", "correctness"))
        ok, results = preflight_check(reg, self._profile(["correctness"]))
        self.assertTrue(ok)
        self.assertEqual(len(results), 1)
        self.assertTrue(results[0].available)

    def test_some_unavailable(self) -> None:
        reg = CollectorRegistry()
        reg.register(_make_config("a", "python3", "correctness"))
        reg.register(_make_config("b", "nonexistent-xyz", "security"))
        ok, results = preflight_check(
            reg, self._profile(["correctness", "security"]),
        )
        self.assertFalse(ok)
        unavailable = [r for r in results if not r.available]
        self.assertEqual(len(unavailable), 1)
        self.assertEqual(unavailable[0].tool, "nonexistent-xyz")

    def test_empty_registry(self) -> None:
        reg = CollectorRegistry()
        ok, results = preflight_check(reg, self._profile(["correctness"]))
        self.assertTrue(ok)
        self.assertEqual(results, [])

    def test_skips_non_applicable_collectors(self) -> None:
        reg = CollectorRegistry()
        reg.register(_make_config("a", "nonexistent-xyz", "performance"))
        ok, results = preflight_check(reg, self._profile(["correctness"]))
        self.assertTrue(ok)
        self.assertEqual(results, [])


if __name__ == "__main__":
    unittest.main()
