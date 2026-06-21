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


def _tsc_cmd(checkout: str, profile: dict[str, Any]) -> list[str]:
    return ["npx", "tsc", "--noEmit"]


def _biome_cmd(checkout: str, profile: dict[str, Any]) -> list[str]:
    return ["npx", "@biomejs/biome", "check", "."]


def _knip_cmd(checkout: str, profile: dict[str, Any]) -> list[str]:
    return ["npx", "knip"]


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

TSC = CollectorConfig(
    collector_id="tsc-static",
    tool="tsc",
    category="static",
    build_cmd=_tsc_cmd,
    tool_version_cmd=("npx", "tsc", "--version"),
    file_patterns=frozenset({"*.ts", "*.tsx"}),
)

BIOME = CollectorConfig(
    collector_id="biome-static",
    tool="biome",
    category="static",
    build_cmd=_biome_cmd,
    tool_version_cmd=("npx", "@biomejs/biome", "--version"),
    file_patterns=frozenset({"*.ts", "*.tsx", "*.js", "*.jsx"}),
)

KNIP = CollectorConfig(
    collector_id="knip-static",
    tool="knip",
    category="static",
    build_cmd=_knip_cmd,
    tool_version_cmd=("npx", "knip", "--version"),
    file_patterns=frozenset({"*.ts", "*.tsx", "*.js", "*.jsx", "*.json"}),
)

COLLECTORS: list[CollectorConfig] = [RUFF, MYPY, TSC, BIOME, KNIP]
