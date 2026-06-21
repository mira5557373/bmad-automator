"""Observability-category evidence collectors (§6.2).

PASS rule: OTel traces/metrics/logs wired; /healthz+/readyz; SLO declared.
Collectors: otel-wiring-observability, health-probe-observability, slo-observability.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from ..collector_config import CollectorConfig

_CHECKS_DIR = Path(__file__).resolve().parent.parent / "checks"

_DEFAULT_SIGNALS = ["traces", "metrics", "logs"]
_DEFAULT_ENDPOINTS = ["/healthz", "/readyz"]
_DEFAULT_SLO_FILES = [
    "slo.yaml",
    "slo.yml",
    "monitoring/slo.yaml",
]


def _otel_wiring_cmd(checkout: str, profile: dict[str, Any]) -> list[str]:
    rules = (profile.get("rules") or {}).get("observability") or {}
    signals = rules.get("required_signals", _DEFAULT_SIGNALS)
    return [
        sys.executable,
        str(_CHECKS_DIR / "otel_check.py"),
        checkout,
        json.dumps(signals),
    ]


def _health_probe_cmd(checkout: str, profile: dict[str, Any]) -> list[str]:
    rules = (profile.get("rules") or {}).get("observability") or {}
    endpoints = rules.get("health_endpoints", _DEFAULT_ENDPOINTS)
    return [
        sys.executable,
        str(_CHECKS_DIR / "health_check.py"),
        checkout,
        json.dumps(endpoints),
    ]


def _slo_cmd(checkout: str, profile: dict[str, Any]) -> list[str]:
    rules = (profile.get("rules") or {}).get("observability") or {}
    slo_files = rules.get("slo_files", _DEFAULT_SLO_FILES)
    return [
        sys.executable,
        str(_CHECKS_DIR / "presence_check.py"),
        checkout,
        json.dumps(slo_files),
    ]


OTEL_WIRING = CollectorConfig(
    collector_id="otel-wiring-observability",
    tool="python3",
    category="observability",
    build_cmd=_otel_wiring_cmd,
    file_patterns=frozenset({"*.py", "*.ts", "*.tsx", "*.js", "*.jsx", "*.yaml", "*.yml"}),
)

HEALTH_PROBE = CollectorConfig(
    collector_id="health-probe-observability",
    tool="python3",
    category="observability",
    build_cmd=_health_probe_cmd,
    file_patterns=frozenset({"*.py", "*.ts", "*.tsx", "*.js", "*.jsx", "*.yaml", "*.yml"}),
)

SLO = CollectorConfig(
    collector_id="slo-observability",
    tool="python3",
    category="observability",
    build_cmd=_slo_cmd,
    file_patterns=frozenset({"*.yaml", "*.yml", "*.json"}),
)

COLLECTORS: list[CollectorConfig] = [OTEL_WIRING, HEALTH_PROBE, SLO]
