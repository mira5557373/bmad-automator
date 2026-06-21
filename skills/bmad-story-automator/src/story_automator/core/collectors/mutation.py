"""Mutation-category evidence collectors (§6.2).

PASS rule: mutation score >= threshold on changed code (sampled/budgeted).
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from ..collector_config import CollectorConfig

_CHECKS_DIR = Path(__file__).resolve().parent.parent / "checks"

_DEFAULT_THRESHOLD = 80


def _mutmut_cmd(checkout: str, profile: dict[str, Any]) -> list[str]:
    rules = (profile.get("rules") or {}).get("mutation") or {}
    threshold = rules.get("threshold", _DEFAULT_THRESHOLD)
    return [
        sys.executable,
        str(_CHECKS_DIR / "mutation_check.py"),
        checkout,
        "mutmut",
        str(int(threshold)),
    ]


def _stryker_cmd(checkout: str, profile: dict[str, Any]) -> list[str]:
    rules = (profile.get("rules") or {}).get("mutation") or {}
    threshold = rules.get("threshold", _DEFAULT_THRESHOLD)
    return [
        sys.executable,
        str(_CHECKS_DIR / "mutation_check.py"),
        checkout,
        "stryker",
        str(int(threshold)),
    ]


MUTMUT = CollectorConfig(
    collector_id="mutmut-mutation",
    tool="python3",
    category="mutation",
    build_cmd=_mutmut_cmd,
    file_patterns=frozenset({"*.py"}),
)

STRYKER = CollectorConfig(
    collector_id="stryker-mutation",
    tool="python3",
    category="mutation",
    build_cmd=_stryker_cmd,
    file_patterns=frozenset({"*.ts", "*.tsx", "*.js", "*.jsx"}),
)

COLLECTORS: list[CollectorConfig] = [MUTMUT, STRYKER]
