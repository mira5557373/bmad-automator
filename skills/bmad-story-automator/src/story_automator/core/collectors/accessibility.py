"""Accessibility-category evidence collectors (§6.2).

PASS rule: axe 0 serious/critical on changed UI.
Collectors: axe-accessibility.
"""
from __future__ import annotations

from typing import Any

from ..collector_config import CollectorConfig


def _axe_cmd(checkout: str, profile: dict[str, Any]) -> list[str]:
    rules = (profile.get("rules") or {}).get("accessibility") or {}
    grep = rules.get("playwright_grep", "@a11y")
    cmd = ["npx", "playwright", "test", "--grep", grep]
    config = rules.get("playwright_config")
    if config:
        cmd.append(f"--config={config}")
    return cmd


AXE = CollectorConfig(
    collector_id="axe-accessibility",
    tool="playwright",
    category="accessibility",
    build_cmd=_axe_cmd,
    tool_version_cmd=("npx", "playwright", "--version"),
    file_patterns=frozenset({"*.ts", "*.tsx", "*.js", "*.jsx"}),
)

COLLECTORS: list[CollectorConfig] = [AXE]
