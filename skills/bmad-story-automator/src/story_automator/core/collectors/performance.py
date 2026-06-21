"""Performance-category evidence collectors (§6.2).

PASS rule: bundle/Lighthouse budgets met; no static N+1/unbounded.
Collectors: lighthouse-performance, bundlesize-performance, perf-lint-performance.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from ..collector_config import CollectorConfig

_CHECKS_DIR = Path(__file__).resolve().parent.parent / "checks"


def _lighthouse_cmd(checkout: str, profile: dict[str, Any]) -> list[str]:
    rules = (profile.get("rules") or {}).get("performance") or {}
    cmd = ["lhci", "autorun"]
    config = rules.get("lhci_config")
    if config:
        cmd.append(f"--config={config}")
    return cmd


def _bundlesize_cmd(checkout: str, profile: dict[str, Any]) -> list[str]:
    return ["npx", "bundlesize"]


def _perf_lint_cmd(checkout: str, profile: dict[str, Any]) -> list[str]:
    rules = (profile.get("rules") or {}).get("performance") or {}
    cmd = [
        sys.executable,
        str(_CHECKS_DIR / "perf_lint_check.py"),
        checkout,
    ]
    extensions = rules.get("lint_extensions")
    if extensions:
        cmd.append(json.dumps(extensions))
    return cmd


LIGHTHOUSE = CollectorConfig(
    collector_id="lighthouse-performance",
    tool="lhci",
    category="performance",
    build_cmd=_lighthouse_cmd,
    tool_version_cmd=("lhci", "--version"),
    file_patterns=frozenset({"*.ts", "*.tsx", "*.js", "*.jsx", "*.css", "*.html"}),
)

BUNDLESIZE = CollectorConfig(
    collector_id="bundlesize-performance",
    tool="bundlesize",
    category="performance",
    build_cmd=_bundlesize_cmd,
    tool_version_cmd=("npx", "bundlesize", "--version"),
    file_patterns=frozenset({"*.ts", "*.tsx", "*.js", "*.jsx", "*.css"}),
)

PERF_LINT = CollectorConfig(
    collector_id="perf-lint-performance",
    tool="python3",
    category="performance",
    build_cmd=_perf_lint_cmd,
    file_patterns=frozenset({"*.py", "*.ts", "*.tsx", "*.js", "*.jsx"}),
)

COLLECTORS: list[CollectorConfig] = [LIGHTHOUSE, BUNDLESIZE, PERF_LINT]
