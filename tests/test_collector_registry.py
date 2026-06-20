from __future__ import annotations

import sys
import unittest
from typing import Any

from story_automator.core.collector_config import CollectorConfig
from story_automator.core.collector_registry import CollectorRegistry


def _noop_cmd(checkout: str, profile: dict[str, Any]) -> list[str]:
    return [sys.executable, "-c", "pass"]


def _make_config(
    collector_id: str = "test-collector",
    tool: str = "test",
    category: str = "correctness",
) -> CollectorConfig:
    return CollectorConfig(
        collector_id=collector_id,
        tool=tool,
        category=category,
        build_cmd=_noop_cmd,
    )


class RegistrationTests(unittest.TestCase):
    def test_register_and_get(self) -> None:
        reg = CollectorRegistry()
        cfg = _make_config("ruff-static", "ruff", "static")
        reg.register(cfg)
        self.assertEqual(reg.get("ruff-static"), cfg)

    def test_get_returns_none_for_unknown(self) -> None:
        reg = CollectorRegistry()
        self.assertIsNone(reg.get("nonexistent"))

    def test_register_duplicate_raises(self) -> None:
        reg = CollectorRegistry()
        cfg = _make_config("dup", "t", "c")
        reg.register(cfg)
        with self.assertRaises(ValueError) as ctx:
            reg.register(cfg)
        self.assertIn("dup", str(ctx.exception))

    def test_all_collectors(self) -> None:
        reg = CollectorRegistry()
        a = _make_config("a", "ta", "ca")
        b = _make_config("b", "tb", "cb")
        reg.register(a)
        reg.register(b)
        result = reg.all_collectors()
        ids = [c.collector_id for c in result]
        self.assertIn("a", ids)
        self.assertIn("b", ids)

    def test_all_collectors_sorted(self) -> None:
        reg = CollectorRegistry()
        reg.register(_make_config("z", "t", "cat-b"))
        reg.register(_make_config("a", "t", "cat-a"))
        result = reg.all_collectors()
        self.assertEqual(
            [(c.category, c.collector_id) for c in result],
            [("cat-a", "a"), ("cat-b", "z")],
        )


class CategoryLookupTests(unittest.TestCase):
    def test_get_for_category(self) -> None:
        reg = CollectorRegistry()
        cfg = _make_config("ruff-static", "ruff", "static")
        reg.register(cfg)
        result = reg.get_for_category("static")
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].collector_id, "ruff-static")

    def test_get_for_category_empty(self) -> None:
        reg = CollectorRegistry()
        self.assertEqual(reg.get_for_category("static"), [])

    def test_multiple_collectors_per_category(self) -> None:
        reg = CollectorRegistry()
        reg.register(_make_config("semgrep-sec", "semgrep", "security"))
        reg.register(_make_config("trivy-sec", "trivy", "security"))
        result = reg.get_for_category("security")
        self.assertEqual(len(result), 2)
        ids = {c.collector_id for c in result}
        self.assertEqual(ids, {"semgrep-sec", "trivy-sec"})

    def test_all_categories(self) -> None:
        reg = CollectorRegistry()
        reg.register(_make_config("a", "t", "static"))
        reg.register(_make_config("b", "t", "security"))
        reg.register(_make_config("c", "t", "static"))
        self.assertEqual(reg.all_categories(), {"static", "security"})

    def test_all_categories_empty(self) -> None:
        reg = CollectorRegistry()
        self.assertEqual(reg.all_categories(), set())


if __name__ == "__main__":
    unittest.main()
