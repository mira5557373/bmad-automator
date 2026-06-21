"""Correctness-category evidence collectors (§6.2).

PASS rule: all tiers green, 0 regressions, line/branch >= risk-required.
Collectors: pytest-correctness (+ vitest, playwright, coverage added later).
"""
from __future__ import annotations

from typing import Any

from ..collector_config import CollectorConfig


def _pytest_cmd(checkout: str, profile: dict[str, Any]) -> list[str]:
    return ["pytest", "--tb=short", "-q"]


def _vitest_cmd(checkout: str, profile: dict[str, Any]) -> list[str]:
    return ["npx", "vitest", "run"]


def _playwright_cmd(checkout: str, profile: dict[str, Any]) -> list[str]:
    return ["npx", "playwright", "test"]


PYTEST = CollectorConfig(
    collector_id="pytest-correctness",
    tool="pytest",
    category="correctness",
    build_cmd=_pytest_cmd,
    tool_version_cmd=("pytest", "--version"),
    file_patterns=frozenset({"*.py"}),
)

VITEST = CollectorConfig(
    collector_id="vitest-correctness",
    tool="vitest",
    category="correctness",
    build_cmd=_vitest_cmd,
    tool_version_cmd=("npx", "vitest", "--version"),
    file_patterns=frozenset({"*.ts", "*.tsx", "*.js", "*.jsx"}),
)

PLAYWRIGHT = CollectorConfig(
    collector_id="playwright-correctness",
    tool="playwright",
    category="correctness",
    build_cmd=_playwright_cmd,
    tool_version_cmd=("npx", "playwright", "--version"),
    file_patterns=frozenset({"*.ts", "*.tsx"}),
)

COLLECTORS: list[CollectorConfig] = [PYTEST, VITEST, PLAYWRIGHT]
