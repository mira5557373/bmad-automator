"""Static-analysis evidence collectors (§6.2).

PASS rule: tsc=0, mypy=0, ruff/Biome=0, deadcode ≤ budget.
Collectors: ruff-static, mypy-static (+ tsc, biome, knip added in Task 4).
"""
from __future__ import annotations

from typing import Any

from ..collector_config import CollectorConfig


def _ruff_cmd(checkout: str, profile: dict[str, Any]) -> list[str]:
    return ["ruff", "check", "."]


def _mypy_cmd(checkout: str, profile: dict[str, Any]) -> list[str]:
    return ["mypy", "."]


RUFF = CollectorConfig(
    collector_id="ruff-static",
    tool="ruff",
    category="static",
    build_cmd=_ruff_cmd,
    tool_version_cmd=("ruff", "--version"),
    file_patterns=frozenset({"*.py"}),
)

MYPY = CollectorConfig(
    collector_id="mypy-static",
    tool="mypy",
    category="static",
    build_cmd=_mypy_cmd,
    tool_version_cmd=("mypy", "--version"),
    file_patterns=frozenset({"*.py", "*.pyi"}),
)

COLLECTORS: list[CollectorConfig] = [RUFF, MYPY]
