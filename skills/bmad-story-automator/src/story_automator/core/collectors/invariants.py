"""Invariants-category evidence collectors (§6.2, §8 module 3).

PASS rule: checkable DG/ADR rules pass (semgrep + conftest).
Collectors: invariant-semgrep-invariants, invariant-conftest-invariants.

The invariant registry lives in profile.rules.invariants.registry as a list
of {id, checkable, check_type, rule_file, severity} dicts.  Each collector
filters by check_type and delegates to invariant_check.py.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from ..collector_config import CollectorConfig

_CHECKS_DIR = Path(__file__).resolve().parent.parent / "checks"


def _invariant_semgrep_cmd(
    checkout: str, profile: dict[str, Any],
) -> list[str]:
    rules = (profile.get("rules") or {}).get("invariants") or {}
    registry = rules.get("registry", [])
    return [
        sys.executable,
        str(_CHECKS_DIR / "invariant_check.py"),
        checkout,
        "semgrep",
        json.dumps(registry),
    ]


def _invariant_conftest_cmd(
    checkout: str, profile: dict[str, Any],
) -> list[str]:
    rules = (profile.get("rules") or {}).get("invariants") or {}
    registry = rules.get("registry", [])
    return [
        sys.executable,
        str(_CHECKS_DIR / "invariant_check.py"),
        checkout,
        "conftest",
        json.dumps(registry),
    ]


INVARIANT_SEMGREP = CollectorConfig(
    collector_id="invariant-semgrep-invariants",
    tool="python3",
    category="invariants",
    build_cmd=_invariant_semgrep_cmd,
    file_patterns=frozenset({"*.py", "*.ts", "*.tsx", "*.js", "*.jsx"}),
)

INVARIANT_CONFTEST = CollectorConfig(
    collector_id="invariant-conftest-invariants",
    tool="python3",
    category="invariants",
    build_cmd=_invariant_conftest_cmd,
    file_patterns=frozenset({"*.yaml", "*.yml", "*.json", "*.tf", "*.hcl"}),
)

COLLECTORS: list[CollectorConfig] = [INVARIANT_SEMGREP, INVARIANT_CONFTEST]
