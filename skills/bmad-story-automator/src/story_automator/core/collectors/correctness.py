"""Correctness-category evidence collectors (§6.2).

PASS rule: all tiers green, 0 regressions, line/branch >= risk-required.
Collectors: pytest-correctness (+ vitest, playwright, coverage added later).
"""
from __future__ import annotations

from typing import Any

from ..collector_config import CollectorConfig


def _pytest_cmd(checkout: str, profile: dict[str, Any]) -> list[str]:
    return ["pytest", "--tb=short", "-q"]


PYTEST = CollectorConfig(
    collector_id="pytest-correctness",
    tool="pytest",
    category="correctness",
    build_cmd=_pytest_cmd,
    tool_version_cmd=("pytest", "--version"),
    file_patterns=frozenset({"*.py"}),
)

COLLECTORS: list[CollectorConfig] = [PYTEST]
