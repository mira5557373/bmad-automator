"""Process/DoD evidence collectors (§6.2).

PASS rule: ADR Production-Readiness section present;
           ACs<->tasks<->tests traced; File List complete.
Collectors: adr-process, trace-process.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from ..collector_config import CollectorConfig

_CHECKS_DIR = Path(__file__).resolve().parent.parent / "checks"


def _adr_cmd(checkout: str, profile: dict[str, Any]) -> list[str]:
    return [
        sys.executable,
        str(_CHECKS_DIR / "adr_check.py"),
        checkout,
    ]


ADR = CollectorConfig(
    collector_id="adr-process",
    tool="python3",
    category="process",
    build_cmd=_adr_cmd,
    file_patterns=frozenset({"*.md"}),
)


def _trace_cmd(checkout: str, profile: dict[str, Any]) -> list[str]:
    return [
        sys.executable,
        str(_CHECKS_DIR / "trace_check.py"),
        checkout,
    ]


TRACE = CollectorConfig(
    collector_id="trace-process",
    tool="python3",
    category="process",
    build_cmd=_trace_cmd,
    file_patterns=frozenset({"*.md"}),
)

COLLECTORS: list[CollectorConfig] = [ADR, TRACE]
