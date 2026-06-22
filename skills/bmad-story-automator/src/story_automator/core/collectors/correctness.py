"""Correctness-category evidence collectors (§6.2).

PASS rule: all tiers green, 0 regressions, line/branch >= risk-required.
Collectors: pytest-correctness, vitest-correctness, playwright-correctness, coverage-correctness.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from ..collector_config import CollectorConfig
from ..metric_parsers import parse_coverage_metrics


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

_CHECKS_DIR = Path(__file__).resolve().parent.parent / "checks"


def _coverage_cmd(checkout: str, profile: dict[str, Any]) -> list[str]:
    matrix = profile.get("matrix") or {}
    p0 = matrix.get("P0") or {}
    threshold = p0.get("coverage_pct", 80)
    return [
        sys.executable,
        str(_CHECKS_DIR / "coverage_check.py"),
        checkout,
        str(int(threshold)),
    ]


COVERAGE = CollectorConfig(
    collector_id="coverage-correctness",
    tool="python3",
    category="correctness",
    build_cmd=_coverage_cmd,
    file_patterns=frozenset({"*.py", "*.ts", "*.tsx"}),
    parse_metrics=parse_coverage_metrics,
)

COLLECTORS: list[CollectorConfig] = [PYTEST, VITEST, PLAYWRIGHT, COVERAGE]
