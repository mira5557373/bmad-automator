from __future__ import annotations

import sys
import unittest
from pathlib import Path
from typing import Any

from story_automator.core.collector_config import (
    CollectorConfig,
    CollectorOutcome,
)


def _echo_cmd(checkout: str, profile: dict[str, Any]) -> list[str]:
    return [sys.executable, "-c", "print('ok')"]


class CollectorConfigCreationTests(unittest.TestCase):
    def test_create_minimal(self) -> None:
        cfg = CollectorConfig(
            collector_id="ruff-static",
            tool="ruff",
            category="static",
            build_cmd=_echo_cmd,
        )
        self.assertEqual(cfg.collector_id, "ruff-static")
        self.assertEqual(cfg.tool, "ruff")
        self.assertEqual(cfg.category, "static")
        self.assertIsNone(cfg.tool_version_cmd)
        self.assertEqual(cfg.file_patterns, frozenset())
        self.assertTrue(cfg.deterministic)

    def test_create_full(self) -> None:
        cfg = CollectorConfig(
            collector_id="semgrep-security",
            tool="semgrep",
            category="security",
            build_cmd=_echo_cmd,
            tool_version_cmd=("semgrep", "--version"),
            file_patterns=frozenset({"*.py", "*.ts"}),
            deterministic=True,
        )
        self.assertEqual(cfg.tool_version_cmd, ("semgrep", "--version"))
        self.assertEqual(cfg.file_patterns, frozenset({"*.py", "*.ts"}))

    def test_frozen(self) -> None:
        cfg = CollectorConfig(
            collector_id="a", tool="t", category="c", build_cmd=_echo_cmd,
        )
        with self.assertRaises(AttributeError):
            cfg.collector_id = "mutated"  # type: ignore[misc]

    def test_build_cmd_callable(self) -> None:
        cfg = CollectorConfig(
            collector_id="a", tool="t", category="c", build_cmd=_echo_cmd,
        )
        cmd = cfg.build_cmd("/checkout", {})
        self.assertEqual(cmd, [sys.executable, "-c", "print('ok')"])

    def test_equality_excludes_build_cmd(self) -> None:
        def other_cmd(checkout: str, profile: dict[str, Any]) -> list[str]:
            return ["other"]

        a = CollectorConfig(
            collector_id="x", tool="t", category="c", build_cmd=_echo_cmd,
        )
        b = CollectorConfig(
            collector_id="x", tool="t", category="c", build_cmd=other_cmd,
        )
        self.assertEqual(a, b)

    def test_hash_excludes_build_cmd(self) -> None:
        def other_cmd(checkout: str, profile: dict[str, Any]) -> list[str]:
            return ["other"]

        a = CollectorConfig(
            collector_id="x", tool="t", category="c", build_cmd=_echo_cmd,
        )
        b = CollectorConfig(
            collector_id="x", tool="t", category="c", build_cmd=other_cmd,
        )
        self.assertEqual(hash(a), hash(b))

    def test_different_ids_not_equal(self) -> None:
        a = CollectorConfig(
            collector_id="x", tool="t", category="c", build_cmd=_echo_cmd,
        )
        b = CollectorConfig(
            collector_id="y", tool="t", category="c", build_cmd=_echo_cmd,
        )
        self.assertNotEqual(a, b)


class CollectorOutcomeTests(unittest.TestCase):
    def test_create_without_path(self) -> None:
        cfg = CollectorConfig(
            collector_id="a", tool="t", category="c", build_cmd=_echo_cmd,
        )
        evidence = {"status": "ok", "category": "c"}
        outcome = CollectorOutcome(config=cfg, evidence=evidence)
        self.assertEqual(outcome.config.collector_id, "a")
        self.assertEqual(outcome.evidence["status"], "ok")
        self.assertIsNone(outcome.persisted_path)

    def test_create_with_path(self) -> None:
        cfg = CollectorConfig(
            collector_id="a", tool="t", category="c", build_cmd=_echo_cmd,
        )
        outcome = CollectorOutcome(
            config=cfg,
            evidence={"status": "ok"},
            persisted_path=Path("/tmp/evidence.json"),
        )
        self.assertEqual(outcome.persisted_path, Path("/tmp/evidence.json"))

    def test_frozen(self) -> None:
        cfg = CollectorConfig(
            collector_id="a", tool="t", category="c", build_cmd=_echo_cmd,
        )
        outcome = CollectorOutcome(config=cfg, evidence={})
        with self.assertRaises(AttributeError):
            outcome.evidence = {}  # type: ignore[misc]


if __name__ == "__main__":
    unittest.main()
