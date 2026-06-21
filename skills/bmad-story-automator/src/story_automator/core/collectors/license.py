"""License-category evidence collectors (§6.2).

PASS rule: 0 forbidden licenses + boundary-aware (AGPL only in Odoo pod).
Collectors: license-check-license.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from ..collector_config import CollectorConfig

_CHECKS_DIR = Path(__file__).resolve().parent.parent / "checks"


def _license_cmd(checkout: str, profile: dict[str, Any]) -> list[str]:
    rules = (profile.get("rules") or {}).get("license") or {}
    forbidden = json.dumps(rules.get("forbidden", []))
    boundary = json.dumps(rules.get("boundary", {}))
    return [
        sys.executable,
        str(_CHECKS_DIR / "license_check.py"),
        checkout,
        forbidden,
        boundary,
    ]


LICENSE_CHECK = CollectorConfig(
    collector_id="license-check-license",
    tool="python3",
    category="license",
    build_cmd=_license_cmd,
    file_patterns=frozenset({"*.lock", "*.txt", "*.toml", "*.cfg", "package.json"}),
)

COLLECTORS: list[CollectorConfig] = [LICENSE_CHECK]
