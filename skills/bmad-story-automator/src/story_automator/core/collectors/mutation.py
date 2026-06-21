"""Mutation-category evidence collectors.

PASS rule: mutation score >= threshold on changed code (sampled/budgeted).
Collectors: mutmut (Python), stryker (JS/TS — future extension).
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from ..collector_config import CollectorConfig

_CHECKS_DIR = Path(__file__).resolve().parent.parent / "checks"
_DEFAULT_MUTATION_THRESHOLD = 60


def _mutmut_cmd(checkout: str, profile: dict[str, Any]) -> list[str]:
    rules = (profile.get("rules") or {}).get("mutation") or {}
    threshold = int(rules.get("min_score", _DEFAULT_MUTATION_THRESHOLD))
    return [
        sys.executable, str(_CHECKS_DIR / "mutation_check.py"),
        checkout, "mutmut", str(threshold),
    ]


MUTMUT = CollectorConfig(
    collector_id="mutmut-mutation",
    tool="python3",
    category="mutation",
    build_cmd=_mutmut_cmd,
    file_patterns=frozenset({"*.py"}),
)

COLLECTORS: list[CollectorConfig] = [MUTMUT]
