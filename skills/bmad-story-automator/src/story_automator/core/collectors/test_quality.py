"""Test-quality-category evidence collectors (§6.2).

PASS rule: TEA test-review >= band; 0 flaky over burn-in N×; no hard-waits.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from ..collector_config import CollectorConfig

_CHECKS_DIR = Path(__file__).resolve().parent.parent / "checks"

_DEFAULT_MIN_SCORE = 70
_DEFAULT_BURN_IN_RUNS = 5
_DEFAULT_MAX_FLAKY = 0
_DEFAULT_BURN_IN_CMD = ["pytest", "-v", "--tb=line"]


def _test_review_cmd(checkout: str, profile: dict[str, Any]) -> list[str]:
    rules = (profile.get("rules") or {}).get("test_quality") or {}
    min_score = rules.get("min_score", _DEFAULT_MIN_SCORE)
    return [
        sys.executable,
        str(_CHECKS_DIR / "test_review_check.py"),
        checkout,
        str(int(min_score)),
    ]


def _burn_in_cmd(checkout: str, profile: dict[str, Any]) -> list[str]:
    rules = (profile.get("rules") or {}).get("test_quality") or {}
    runs = rules.get("burn_in_runs", _DEFAULT_BURN_IN_RUNS)
    max_flaky = rules.get("max_flaky", _DEFAULT_MAX_FLAKY)
    test_cmd = rules.get("burn_in_cmd", _DEFAULT_BURN_IN_CMD)
    return [
        sys.executable,
        str(_CHECKS_DIR / "burn_in_check.py"),
        checkout,
        str(int(runs)),
        str(int(max_flaky)),
        json.dumps(test_cmd),
    ]


def _hard_wait_cmd(checkout: str, profile: dict[str, Any]) -> list[str]:
    return [
        sys.executable,
        str(_CHECKS_DIR / "hard_wait_check.py"),
        checkout,
    ]


TEST_REVIEW = CollectorConfig(
    collector_id="test-review-test_quality",
    tool="python3",
    category="test_quality",
    build_cmd=_test_review_cmd,
    file_patterns=frozenset({"*.py", "*.ts", "*.tsx", "*.js", "*.jsx"}),
)

BURN_IN = CollectorConfig(
    collector_id="burn-in-test_quality",
    tool="python3",
    category="test_quality",
    build_cmd=_burn_in_cmd,
    file_patterns=frozenset({"*.py", "*.ts", "*.tsx", "*.js", "*.jsx"}),
)

HARD_WAIT = CollectorConfig(
    collector_id="hard-wait-test_quality",
    tool="python3",
    category="test_quality",
    build_cmd=_hard_wait_cmd,
    file_patterns=frozenset({"*.py", "*.ts", "*.tsx", "*.js", "*.jsx"}),
)

COLLECTORS: list[CollectorConfig] = [TEST_REVIEW, BURN_IN, HARD_WAIT]
