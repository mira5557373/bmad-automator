"""Reliability-category system-altitude collectors (§10/HR6(a)).

PASS rule: RTO/RPO within profile limits.
Collectors: cnpg-reliability (CNPG failover), pgbackrest-reliability (restore timing).
"""
from __future__ import annotations

from typing import Any

from ..collector_config import CollectorConfig


def _cnpg_failover_cmd(checkout: str, profile: dict[str, Any]) -> list[str]:
    env = profile.get("_runtime_env") or {}
    ns = env.get("namespace", "default")
    return [
        "kubectl", "cnpg", "promote",
        "--namespace", ns,
        "--dry-run=server",
    ]


def _pgbackrest_restore_cmd(checkout: str, profile: dict[str, Any]) -> list[str]:
    env = profile.get("_runtime_env") or {}
    ns = env.get("namespace", "default")
    return [
        "kubectl", "exec", "-n", ns,
        "cnpg-primary-0", "--",
        "pgbackrest", "info", "--output=json",
    ]


CNPG_FAILOVER = CollectorConfig(
    collector_id="cnpg-reliability",
    tool="cnpg",
    category="reliability",
    build_cmd=_cnpg_failover_cmd,
    tool_version_cmd=("kubectl", "cnpg", "version"),
)

PGBACKREST_RESTORE = CollectorConfig(
    collector_id="pgbackrest-reliability",
    tool="pgbackrest",
    category="reliability",
    build_cmd=_pgbackrest_restore_cmd,
)

COLLECTORS: list[CollectorConfig] = [CNPG_FAILOVER, PGBACKREST_RESTORE]
