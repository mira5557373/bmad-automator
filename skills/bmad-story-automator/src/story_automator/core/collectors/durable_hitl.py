"""Durable-HITL-category system-altitude collector (§10/HR6(c)).

PASS rule: Temporal signal survived pod kill.
Collector: temporal-durable-hitl.
"""
from __future__ import annotations

from typing import Any

from ..collector_config import CollectorConfig


def _temporal_signal_cmd(checkout: str, profile: dict[str, Any]) -> list[str]:
    env = profile.get("_runtime_env") or {}
    ns = env.get("namespace", "default")
    return [
        "kubectl", "exec", "-n", ns,
        "temporal-admin-tools-0", "--",
        "tctl", "workflow", "list", "--status", "completed",
        "--output", "json",
    ]


TEMPORAL_SIGNAL = CollectorConfig(
    collector_id="temporal-durable-hitl",
    tool="temporal",
    category="durable_hitl",
    build_cmd=_temporal_signal_cmd,
    tool_version_cmd=("tctl", "version"),
)

COLLECTORS: list[CollectorConfig] = [TEMPORAL_SIGNAL]
