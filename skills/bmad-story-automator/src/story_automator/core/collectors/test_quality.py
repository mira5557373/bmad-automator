"""Test-quality-category evidence collectors.

PASS rule: TEA test-review >= band; 0 flaky over burn-in N runs; no hard-waits.
Collectors: burn-in, hard-wait scanner, TEA test-review reader.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from ..collector_config import CollectorConfig

_CHECKS_DIR = Path(__file__).resolve().parent.parent / "checks"
_DEFAULT_BURN_IN_RUNS = 5
_DEFAULT_MIN_SCORE = 70


def _burn_in_cmd(checkout: str, profile: dict[str, Any]) -> list[str]:
    rules = (profile.get("rules") or {}).get("test_quality") or {}
    n_runs = int(rules.get("burn_in_runs", _DEFAULT_BURN_IN_RUNS))
    timeouts = profile.get("timeouts") or {}
    total_timeout = int(timeouts.get("test_quality", 900))
    per_run = max(60, total_timeout // max(n_runs, 1))
    return [
        sys.executable, str(_CHECKS_DIR / "burn_in_check.py"),
        checkout, str(n_runs), "--timeout", str(per_run),
        "--", "pytest", "--tb=short", "-q",
    ]


def _hard_wait_cmd(checkout: str, profile: dict[str, Any]) -> list[str]:
    return [
        sys.executable, str(_CHECKS_DIR / "hard_wait_check.py"),
        checkout,
    ]


def _test_review_cmd(checkout: str, profile: dict[str, Any]) -> list[str]:
    rules = (profile.get("rules") or {}).get("test_quality") or {}
    min_score = int(rules.get("min_score", _DEFAULT_MIN_SCORE))
    return [
        sys.executable, str(_CHECKS_DIR / "test_review_check.py"),
        checkout, str(min_score),
    ]


BURN_IN = CollectorConfig(
    collector_id="burn-in-test-quality",
    tool="python3",
    category="test_quality",
    build_cmd=_burn_in_cmd,
    file_patterns=frozenset({"*.py", "*.ts", "*.tsx", "*.js", "*.jsx"}),
)

HARD_WAIT = CollectorConfig(
    collector_id="hard-wait-test-quality",
    tool="python3",
    category="test_quality",
    build_cmd=_hard_wait_cmd,
    file_patterns=frozenset({"*.py", "*.ts", "*.tsx", "*.js", "*.jsx"}),
)

TEST_REVIEW = CollectorConfig(
    collector_id="test-review-test-quality",
    tool="python3",
    category="test_quality",
    build_cmd=_test_review_cmd,
    deterministic=False,
    file_patterns=frozenset({"*.py", "*.ts", "*.tsx", "*.js", "*.jsx"}),
)

COLLECTORS: list[CollectorConfig] = [BURN_IN, HARD_WAIT, TEST_REVIEW]
