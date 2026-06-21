"""Traceability-category evidence collectors (§6.2).

PASS rule: P0 ACs 100% / P1 >= 90% mapped to tests.
Evidence: TEA e2e-trace-summary.json (fallback: GWT title parse).
Collectors: trace-traceability.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from ..collector_config import CollectorConfig

_CHECKS_DIR = Path(__file__).resolve().parent.parent / "checks"

_DEFAULT_THRESHOLDS = {"P0": 100, "P1": 90}


def _trace_cmd(checkout: str, profile: dict[str, Any]) -> list[str]:
    matrix = profile.get("matrix") or {}
    thresholds: dict[str, int] = {}
    for pri, defaults in _DEFAULT_THRESHOLDS.items():
        pri_cfg = matrix.get(pri) or {}
        thresholds[pri] = pri_cfg.get("coverage_pct", defaults)
    cmd = [
        sys.executable,
        str(_CHECKS_DIR / "traceability_check.py"),
        checkout,
        json.dumps(thresholds),
    ]
    rules = (profile.get("rules") or {}).get("traceability") or {}
    tea_path = rules.get("tea_trace_path")
    if tea_path:
        cmd.append(tea_path)
    return cmd


TRACE = CollectorConfig(
    collector_id="trace-traceability",
    tool="python3",
    category="traceability",
    build_cmd=_trace_cmd,
    file_patterns=frozenset({"*.md", "*.json", "*.py"}),
)

COLLECTORS: list[CollectorConfig] = [TRACE]
